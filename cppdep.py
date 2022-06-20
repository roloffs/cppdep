#!/usr/bin/env python

import os
import sys
import subprocess
import argparse
import json

from jinja2 import Environment, FileSystemLoader


class SourceFile:
    file_extensions = {'.cpp', '.cc', '.c++', '.hpp', '.h', '.inl'}

    def __init__(self, file_path, root_file=False, main_file=False, missing=False):
        self.file_path = file_path
        self.root_file = root_file
        self.main_file = main_file
        self.missing = missing
        self.component = None
        self.includes = list()

    def id(self):
        return self.file_path

    def name(self):
        return os.path.basename(self.id())

    def node_str(self):
        return f'''
        "{self.id()}" [
            shape=box,
            style=filled,
            color={'blue' if self.root_file else 'black'},
            penwidth={2 if self.root_file else 1},
            fillcolor={'green' if self.main_file else 'red' if self.missing else 'white'},
            margin="0.1,0",
            label="{self.name()}"];'''

    def edge_str(self):
        return f'"{self.id()}"'


class Component:
    def __init__(self):
        self.source_files = list()

    def add_source_file(self, source_file):
        self.source_files.append(source_file)
        source_file.component = self

    def id(self):
        return f'cluster_{os.path.splitext(self.source_files[0].id())[0]}'

    def name(self):
        return os.path.basename(self.id())

    def node_str(self):
        newline='\n'
        return f'''subgraph "{self.id()}" {{
        rank=same;
        label="{self.name()}";
        style=filled;
        fillcolor=lightgrey;
{newline.join([file.node_str() for file in self.source_files])}
    }}'''


def find_source_files(source_dirs):
    source_dirs = list(set(map(os.path.abspath, source_dirs)))
    source_files = dict()

    # scan source dirs for source files
    for source_dir in source_dirs:
        for root, dirs, files in os.walk(source_dir):
            for filename in files:
                file_root, file_ext = os.path.splitext(filename)

                # check for source file
                if file_ext.lower() in SourceFile.file_extensions:
                    file_path = os.path.join(root, filename)
                    source_files[file_path] = SourceFile(file_path)

    return source_files


def find_path(include_path, include_dirs, local_dir):
    # first fit search in include dirs
    for include_dir in include_dirs:
        file_path = os.path.join(include_dir, include_path)
        if os.path.exists(file_path):
            return file_path

    # check local dir
    file_path = os.path.join(local_dir, include_path)
    if os.path.exists(file_path):
        return file_path

    return None


def preprocess_source_files(source_files, include_dirs, macros):
    include_dirs = list(set(map(os.path.abspath, include_dirs)))
    new_source_files = dict()
    out_source_files = dict()

    def preprocess_source_file(source_file, include_dirs, macros):
        if source_file.file_path in out_source_files:
            return
        out_source_files[source_file.file_path] = source_file

        if source_file.missing:
            return

        # grep for main function in source file
        grep_cmd = ['grep', r'^\s*\bint\b\s*\bmain\b', source_file.file_path]
        # print(' '.join(grep_cmd))
        process = subprocess.run(
            grep_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if process.returncode == 0:
            source_file.main_file = True

        # extract dependencies from source file
        macro_flags = [f'-D{macro}' for macro in macros]
        compile_cmd = ['g++', '-I-', '-MM', '-MG'] + macro_flags + ['-x', 'c++', source_file.file_path]
        print(' '.join(compile_cmd))
        process = subprocess.run(
            compile_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        source_file.includes.clear()
        if process.returncode == 0:
            includes = process.stdout.replace('\\', '').split()
            if not includes:
                return

            for include_path in list(map(os.path.normpath, includes[2:])):
                local_dir = os.path.dirname(source_file.file_path)
                file_path = find_path(include_path, include_dirs, local_dir)
                # print(f'Lookup {include_path} in include dirs -> {file_path}')

                if file_path:
                    if file_path in source_files:
                        child = source_files[file_path]
                    elif file_path in new_source_files:
                        child = new_source_files[file_path]
                    else:
                        child = SourceFile(file_path)
                        new_source_files[file_path] = child

                else:
                    if include_path in source_files:
                        child = source_files[include_path]
                    elif include_path in new_source_files:
                        child = new_source_files[include_path]
                    else:
                        print(f'Included file not found: {include_path}')
                        child = SourceFile(include_path, missing=True)
                        new_source_files[include_path] = child

                source_file.includes.append(child)
                preprocess_source_file(child, include_dirs, macros)

        else:
            print(f'Compile error for {source_file.file_path}:\n{process.stderr}')
            # sys.exit(1)

    for source_file in source_files.values():
        preprocess_source_file(source_file, include_dirs, macros)

    return out_source_files


def component_analysis(source_files):
    components = list()

    for source_file1 in source_files.values():
        file_root1, file_ext1 = os.path.splitext(os.path.basename(source_file1.file_path))

        for source_file2 in source_file1.includes:
            file_root2, file_ext2 = os.path.splitext(os.path.basename(source_file2.file_path))

            if file_root1 == file_root2 and file_ext1 != file_ext2:
                if source_file1.component and source_file2.component:
                    continue

                elif source_file1.component and not source_file2.component:
                    source_file1.component.add_source_file(source_file2)

                elif not source_file1.component and source_file2.component:
                    source_file2.component.add_source_file(source_file1)

                else:
                    component = Component()
                    component.add_source_file(source_file1)
                    component.add_source_file(source_file2)
                    components.append(component)

    for source_file in source_files.values():
        if not source_file.component:
            component = Component()
            component.add_source_file(source_file)
            components.append(component)

    return components


def get_source_files(file_paths, source_files_db):
    file_paths = list(set(map(os.path.abspath, file_paths)))
    source_files = dict()

    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f'File not found: {file_path}')
            sys.exit(1)

        if file_path not in source_files_db:
            source_files_db[file_path] = SourceFile(file_path)

        source_file = source_files_db[file_path]
        source_files[file_path] = source_file

    return source_files


def get_connected_graphs(source_files):
    out_source_files = dict()

    def visit(node):
        if node.file_path in out_source_files:
            return
        out_source_files[node.file_path] = node
        for child in node.includes:
            visit(child)

    for source_file in source_files.values():
        source_file.root_file = True
        visit(source_file)

    return out_source_files


def transitive_reduction(source_files):
    # transitive reduction
    temp_mark = dict()
    permanent_mark = dict()
    reachable_nodes = dict()

    for source_file in source_files.values():
        temp_mark[source_file] = False
        permanent_mark[source_file] = False
        reachable_nodes[source_file] = set()

    def visit(node):
        if permanent_mark[node]:
            # already visited
            return

        if temp_mark[node]:
            # cycle detected
            return

        temp_mark[node] = True
        for child in node.includes:
            visit(child)

        for child1 in node.includes.copy():
            for child2 in node.includes.copy():
                if child1 != child2 and child1 in reachable_nodes[child2]:
                    node.includes.remove(child1)
                    break

        for child in node.includes:
            reachable_nodes[node].add(child)
            reachable_nodes[node].update(reachable_nodes[child])

        temp_mark[node] = False
        permanent_mark[node] = True

    for source_file in source_files.values():
        visit(source_file)


def render_graph(graph_dict, outfile):
    script_path = os.path.dirname(os.path.realpath(__file__))
    env = Environment(
        loader=FileSystemLoader(script_path),
        trim_blocks=True,
        lstrip_blocks=True
    )
    graph_template = env.get_template('graph.j2')
    graph_template.stream(graph_dict).dump(outfile)
    print(outfile + ' has been written')


def to_dict(obj):
    return json.loads(json.dumps(obj, default=vars))


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_file', metavar='source-file', nargs='*')
    parser.add_argument('-S', '--source_dir', metavar='source-dir', action='append', default=list())
    parser.add_argument('-I', '--include_dir', metavar='include-dir', action='append', default=list())
    parser.add_argument('-D', '--macro', action='append', default=list())
    parser.add_argument('-o', '--outfile', nargs=1, default='graph.dot')
    return parser.parse_args()


def main():
    args = parse_arguments()
    source_files = find_source_files(args.source_dir)
    source_files = preprocess_source_files(source_files, args.include_dir, args.macro)
    components = component_analysis(source_files)

    # source_files = get_source_files(args.source_file, source_files_db)
    # preprocess_source_files(source_files, source_files_db, args.include_dir, args.macro)

    transitive_reduction(source_files)
    # source_files = get_connected_graphs(source_files)

    render_graph({"source_files": source_files.values(), "components": components}, args.outfile)

    return 0

if __name__ == '__main__':
    sys.exit(main())
