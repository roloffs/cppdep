#!/usr/bin/env python

import argparse
import os
import subprocess
import sys

from jinja2 import Environment, FileSystemLoader


class SourceFile:
    file_extensions = {".cpp", ".cc", ".c++", ".hpp", ".h", ".inl"}
    display_path = False
    max_path_length = 30

    def __init__(self, file_path, missing=False):
        self.file_path = file_path
        self.missing = missing
        self.main_file = False
        self.root_file = False
        self.preprocessed = False
        self.compile_error = False
        self.component = None
        self.includes = []

    def id(self):
        return self.file_path

    def name(self):
        return os.path.basename(self.id())

    def path(self):
        file_path = os.path.relpath(self.id())
        # Insert a line break for long paths at the slash that is closest to the
        # middle.
        if len(file_path) > SourceFile.max_path_length:
            mid_index = len(file_path) // 2
            index1 = file_path.rfind("/", 0, mid_index)
            index2 = file_path.find("/", mid_index)
            index = mid_index
            if index1 != -1 and index2 == -1:
                index = index1
            elif index1 == -1 and index2 != -1:
                index = index2
            elif index1 != -1 and index2 != -1:
                index1_diff = mid_index - index1
                index2_diff = index2 - mid_index
                if index1_diff < index2_diff:
                    index = index1
                elif index2_diff < index1_diff:
                    index = index2
                else:
                    index = index2
            return f"{file_path[:index]}\n{file_path[index:]}"
        return file_path

    def node_str(self):
        return f""""{self.id()}" [
            shape=box,
            style=filled,
            color={'blue' if self.root_file else 'black'},
            penwidth={2 if self.root_file else 1},
            fillcolor={'green' if self.main_file else 'red' if self.missing else 'blue' if self.compile_error else 'white'},
            margin="0.1,0",
            label="{self.path() if SourceFile.display_path else self.name()}"];"""

    def edge_str(self):
        return f'"{self.id()}"'

    def __str__(self):
        return self.id()


class Component:
    def __init__(self):
        self.source_files = []

    def add_source_file(self, source_file):
        self.source_files.append(source_file)
        source_file.component = self

    def id(self):
        return f"cluster_{os.path.splitext(self.source_files[0].id())[0]}"

    def name(self):
        return os.path.basename(self.id())

    def node_str(self):
        newline = "\n"
        return f"""subgraph "{self.id()}" {{
        rank=same;
        label="{self.name()}";
        style=filled;
        penwidth=2;
        fillcolor=lightgrey;

        {f"{newline}{newline}        ".join([file.node_str() for file in self.source_files])}
    }}"""

    def __str__(self):
        return self.id()


def find_source_files(source_dirs):
    source_dirs = list(set(map(os.path.abspath, source_dirs)))
    source_files = {}

    # Scan source dirs for source files.
    for source_dir in source_dirs:
        # print(f"Find source files recursively in {source_dir}")
        for root, _, files in os.walk(source_dir):
            for filename in files:
                _, file_ext = os.path.splitext(filename)

                # Check for source file.
                if file_ext.lower() in SourceFile.file_extensions:
                    file_path = os.path.join(root, filename)
                    source_files[file_path] = SourceFile(file_path)

    return source_files


def find_include_file(include_path, include_dirs, local_dir):
    # First fit search in include dirs.
    for include_dir in include_dirs:
        file_path = os.path.join(include_dir, include_path)
        if os.path.exists(file_path):
            return file_path

    # Successively go up in the file hierarchy of local dir and check whether
    # appending the include path results in an existing file.
    tmp_dir = local_dir
    while tmp_dir != "/":
        file_path = os.path.join(tmp_dir, include_path)
        if os.path.exists(file_path):
            return file_path
        tmp_dir = os.path.dirname(tmp_dir)

    return None


def preprocess_source_file(
    source_file, source_files, include_files, include_dirs, macros
):
    if source_file.preprocessed or source_file.missing:
        return
    source_file.preprocessed = True
    # print(f"Preprocess {source_file}")

    # Check for main function in source file.
    grep_cmd = [
        "grep",
        "-E",
        r"^\s*\b(int|auto)\b\s*\bmain\b\s*\(.*\)",
        source_file.file_path,
    ]
    # print(" ".join(grep_cmd))
    process = subprocess.run(
        grep_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode == 0:
        source_file.main_file = True

    # Extract dependencies from source file.
    macro_flags = [f"-D{macro}" for macro in macros]
    compile_cmd = (
        ["g++", "-MM", "-MG"]
        + macro_flags
        + ["-x", "c++", source_file.file_path]
    )
    # print(" ".join(compile_cmd))
    process = subprocess.run(
        compile_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=False,
    )

    if process.returncode == 0:
        includes = process.stdout.replace("\\", "").split()
        if not includes:
            return

        for include_path in list(map(os.path.normpath, includes[2:])):
            local_dir = os.path.dirname(source_file.file_path)
            file_path = find_include_file(include_path, include_dirs, local_dir)
            # print(f"Lookup {include_path} -> {file_path}")

            if file_path:
                if file_path in source_files:
                    child = source_files[file_path]
                elif file_path in include_files:
                    child = include_files[file_path]
                else:
                    child = SourceFile(file_path)
                    include_files[file_path] = child

            else:
                if include_path in source_files:
                    child = source_files[include_path]
                elif include_path in include_files:
                    child = include_files[include_path]
                else:
                    # print(f"Included file not found: {include_path}")
                    child = SourceFile(include_path, missing=True)
                    include_files[include_path] = child

            source_file.includes.append(child)
            preprocess_source_file(
                child, source_files, include_files, include_dirs, macros
            )

    else:
        # print(f"Compile error for {source_file.file_path}:\n{process.stderr}")
        source_file.compile_error = True


def preprocess_source_files(source_files, include_dirs, macros):
    include_dirs = list(set(map(os.path.abspath, include_dirs)))
    include_files = {}
    for source_file in source_files.values():
        preprocess_source_file(
            source_file, source_files, include_files, include_dirs, macros
        )
    return source_files | include_files


def component_analysis(source_files):
    components = []

    # Create multi-file components.
    for source_file1 in source_files.values():
        file_root1, file_ext1 = os.path.splitext(
            os.path.basename(source_file1.file_path)
        )

        for source_file2 in source_file1.includes:
            file_root2, file_ext2 = os.path.splitext(
                os.path.basename(source_file2.file_path)
            )

            if file_root1 == file_root2 and file_ext1 != file_ext2:
                if source_file1.component and source_file2.component:
                    pass

                elif source_file1.component and not source_file2.component:
                    source_file1.component.add_source_file(source_file2)

                elif not source_file1.component and source_file2.component:
                    source_file2.component.add_source_file(source_file1)

                else:
                    component = Component()
                    component.add_source_file(source_file1)
                    component.add_source_file(source_file2)
                    components.append(component)

    # Create single-file components.
    for source_file in source_files.values():
        if not source_file.component:
            component = Component()
            component.add_source_file(source_file)
            components.append(component)

    return components


def transitive_reduction(source_files):
    # Transitive reduction.
    temp_mark = {}
    permanent_mark = {}
    reachable_nodes = {}

    for source_file in source_files.values():
        temp_mark[source_file] = False
        permanent_mark[source_file] = False
        reachable_nodes[source_file] = set()

    def visit(node):
        if permanent_mark[node]:
            # Already visited.
            return

        if temp_mark[node]:
            # Cycle detected.
            return

        temp_mark[node] = True
        for child in node.includes:
            visit(child)

        for child1 in node.includes.copy():
            # Do not remove intra-component edges.
            if child1.component is node.component:
                continue
            for child2 in node.includes.copy():
                if child2 is child1:
                    continue
                if child1 in reachable_nodes[child2]:
                    node.includes.remove(child1)
                    break

        for child in node.includes:
            reachable_nodes[node].add(child)
            reachable_nodes[node].update(reachable_nodes[child])

        temp_mark[node] = False
        permanent_mark[node] = True

    for source_file in source_files.values():
        visit(source_file)

    return source_files


def render_graph(graph_dict, outfile):
    script_path = os.path.dirname(os.path.realpath(__file__))
    env = Environment(
        loader=FileSystemLoader(script_path),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    graph_template = env.get_template("graph.j2")
    graph_template.stream(graph_dict).dump(outfile)
    print(f"'{outfile}' has been written")


def parse_arguments():
    parser = argparse.ArgumentParser()
    # Define arguments.
    parser.add_argument(
        "source_file",
        # action="store",
        nargs="*",
        # default=[],
    )
    # Define options.
    parser.add_argument(
        "-p",
        "--display_path",
        action="store_true",
        # nargs=0,
        # default=False,
    )
    parser.add_argument(
        "-s",
        "--source_dir",
        action="append",
        # nargs=1,
        default=[],
    )
    parser.add_argument(
        "-i",
        "--include_dir",
        action="append",
        # nargs=1,
        default=[],
    )
    parser.add_argument(
        "-m",
        "--macro",
        action="append",
        # nargs=1,
        default=[],
    )
    parser.add_argument(
        "-o",
        "--outfile",
        # action="store",
        # nargs=1,
        default="graph.dot",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    SourceFile.display_path = args.display_path
    source_files = find_source_files(args.source_dir)
    source_files = preprocess_source_files(
        source_files, args.include_dir, args.macro
    )
    components = component_analysis(source_files)
    source_files = transitive_reduction(source_files)
    render_graph(
        {"source_files": source_files.values(), "components": components},
        args.outfile,
    )


if __name__ == "__main__":
    sys.exit(main())
