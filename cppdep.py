#!/usr/bin/env python

import os
import sys
import subprocess
import argparse
import json

from jinja2 import Environment, FileSystemLoader

class HeaderFile:
    file_extensions = {'.hpp', '.h', '.inl'}

    def __init__(self, include_path, file_path=None):
        self.include_path = include_path
        self.file_path = file_path
        self.includes = list()
        self.component = None

    def id(self):
        return self.include_path

    def name(self):
        return os.path.basename(self.include_path)

    def row_str(self):
        return f'''<tr><td port="{self.name()}"{' bgcolor="red"' if not self.file_path else ''}>{self.name()}</td></tr>'''

    def node_str(self):
        return f'''"{self.id()}" [label=<
        <table>
            {self.row_str()}
        </table>>];'''

    def edge_str(self):
        if self.component:
            return f'"{self.component.id()}":"{self.name()}"'
        else:
            return f'"{self.id()}"'

class SourceFile:
    file_extensions = {'.cpp', '.cc', '.c++'}

    def __init__(self, main_file, file_path):
        self.main_file = main_file
        self.file_path = file_path
        self.includes = list()
        self.component = None

    def id(self):
        return self.file_path

    def name(self):
        return os.path.basename(self.file_path)

    def row_str(self):
        return f'''<tr><td port="{self.name()}"{' bgcolor="green"' if self.main_file else ''}>{self.name()}</td></tr>'''

    def node_str(self):
        return f'''"{self.id()}" [label=<
        <table>
            {self.row_str()}
        </table>>];'''

    def edge_str(self):
        if self.component:
            return f'"{self.component.id()}":"{self.name()}"'
        else:
            return f'"{self.id()}"'

class Component:
    def __init__(self, source_file, header_file):
        self.source_file = source_file
        self.header_file = header_file
        source_file.component = self
        header_file.component = self

    def id(self):
        return os.path.splitext(self.source_file.id())[0]

    def name(self):
        return os.path.basename(self.source_file.id())

    def node_str(self):
        return f'''"{self.id()}" [label=<
        <table bgcolor="lightblue">
            {self.header_file.row_str()}
            {self.source_file.row_str()}
        </table>>];'''

class Project:
    def __init__(self):
        self.header_files_lookup = dict()
        self.header_files = list()
        self.source_files = list()
        self.components = list()

    def scan_include_dirs(self, include_dirs):
        header_dups = dict()

        # scan all include directories recursively for header files
        for include_dir in include_dirs:
            include_dir = os.path.expanduser(include_dir)

            for root, dirs, files in os.walk(include_dir):
                base_dir = os.path.relpath(root, include_dir)

                for filename in files:
                    file_root, file_ext = os.path.splitext(filename)
                    file_path = os.path.normpath(os.path.join(root, filename))

                    # check for header file
                    if file_ext in HeaderFile.file_extensions:
                        include_path = os.path.normpath(os.path.join(base_dir, filename))
                        header_file = HeaderFile(include_path, file_path)

                        # check for duplicates
                        if include_path in self.header_files_lookup:
                            if include_path not in header_dups:
                                header_dups[include_path] = set()
                                header_dups[include_path].add(self.header_files_lookup[include_path])
                            header_dups[include_path].add(header_file)

                        else:
                            self.header_files.append(header_file)
                            self.header_files_lookup[include_path] = header_file
                            self.header_files_lookup[file_path] = header_file

        # check header duplicates
        if header_dups:
            for include_path, header_files in header_dups.items():
                print(include_path + ':')
                for header_file in header_files:
                    print('  ' + header_file.file_path)

            sys.exit(1)

    def scan_source_dirs(self, source_dirs):
        # scan all source directories recursively for source and header files
        for source_dir in source_dirs:
            source_dir = os.path.expanduser(source_dir)

            for root, dirs, files in os.walk(source_dir):
                for filename in files:
                    file_root, file_ext = os.path.splitext(filename)
                    file_path = os.path.normpath(os.path.join(root, filename))

                    # check for source file
                    if file_ext in SourceFile.file_extensions:
                        # grep for main function in source file
                        process = subprocess.run(
                            ['grep', r'\s*\bint\b\s*\bmain\b', file_path],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        source_file = SourceFile(process.returncode == 0, file_path)
                        self.source_files.append(source_file)

                    # check for header file
                    elif file_ext in HeaderFile.file_extensions:
                        header_file = HeaderFile(file_path, file_path)
                        self.header_files.append(header_file)
                        self.header_files_lookup[file_path] = header_file

    def preprocess_header_files(self, macros):
        macro_flags = [f'-D{macro}' for macro in macros]
        compile_cmd = ['g++', '-MM', '-MG'] + macro_flags + ['-x', 'c++']

        for header_file in self.header_files.copy():
            # print(' '.join(compile_cmd) + ' ' + header_file.file_path)

            process = subprocess.run(
                compile_cmd + [header_file.file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            if process.returncode == 0:
                # parse dependency string
                includes = process.stdout.replace('\\', '').split()
                if includes:
                    # ignore first two entries
                    for include_path in includes[2:]:
                        if include_path in self.header_files_lookup:
                            found_header_file = self.header_files_lookup[include_path]
                            if found_header_file != header_file:
                                header_file.includes.append(found_header_file)

                        else:
                            missing_header_file = HeaderFile(include_path)
                            header_file.includes.append(missing_header_file)
                            self.header_files.append(missing_header_file)
                            self.header_files_lookup[include_path] = missing_header_file

                else:
                    print('No dependencies for ' + header_file.file_path)

            else:
                print('Compile error for ' + header_file.file_path + ':\n' + process.stderr)

    def preprocess_source_files(self, macros):
        macro_flags = [f'-D{macro}' for macro in macros]
        compile_cmd = ['g++', '-MM', '-MG'] + macro_flags + ['-x', 'c++']

        for source_file in self.source_files.copy():
            # print(' '.join(compile_cmd) + ' ' + source_file.file_path)

            process = subprocess.run(
                compile_cmd + [source_file.file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            if process.returncode == 0:
                # parse dependency string
                includes = process.stdout.replace('\\', '').split()
                if includes:
                    # ignore first two entries
                    for include_path in includes[2:]:
                        if include_path in self.header_files_lookup:
                            source_file.includes.append(self.header_files_lookup[include_path])

                        else:
                            missing_header_file = HeaderFile(include_path)
                            source_file.includes.append(missing_header_file)
                            self.header_files.append(missing_header_file)
                            self.header_files_lookup[include_path] = missing_header_file

                else:
                    print('No dependencies for ' + source_file.file_path)

            else:
                print('Compile error for ' + source_file.file_path + ':\n' + process.stderr)

    def transitive_reduction(self):
        permanent_mark = dict()
        reachable_nodes = dict()
        temp_mark = dict()

        for header_file in self.header_files:
            permanent_mark[header_file] = False
            reachable_nodes[header_file] = set()
            temp_mark[header_file] = False

        for source_file in self.source_files:
            permanent_mark[source_file] = False
            reachable_nodes[source_file] = set()
            temp_mark[source_file] = False

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

            nodes = node.includes.copy()
            for child1 in nodes:
                for child2 in nodes:
                    if child1 in reachable_nodes[child2]:
                        node.includes.remove(child1)
                        break

            for child in node.includes:
                reachable_nodes[node].add(child)
                reachable_nodes[node].update(reachable_nodes[child])

            temp_mark[node] = False
            permanent_mark[node] = True

        for header_file in self.header_files:
            visit(header_file)

        for source_file in self.source_files:
            visit(source_file)

    def component_partitioning(self):
        for source_file in self.source_files.copy():
            file_root1, file_ext1 = os.path.splitext(os.path.basename(source_file.file_path))

            for header_file in source_file.includes.copy():
                file_root2, file_ext2 = os.path.splitext(os.path.basename(header_file.include_path))

                if file_root1 == file_root2 and file_ext1 != file_ext2:
                    if source_file.component and header_file.component:
                        # print('Source file includes a second header file of same name: ' + source_file.file_path)
                        pass

                    elif source_file.component and not header_file.component:
                        # print('Source file includes a second header file of same name: ' + source_file.file_path)
                        pass

                    elif not source_file.component and header_file.component:
                        # print('Second source file includes header file of same name: ' + source_file.file_path)
                        pass

                    else:
                        component = Component(source_file, header_file)
                        self.components.append(component)
                        self.source_files.remove(source_file)
                        self.header_files.remove(header_file)

        for header_file1 in self.header_files.copy():
            file_root1, file_ext1 = os.path.splitext(os.path.basename(header_file1.include_path))

            for header_file2 in header_file1.includes.copy():
                file_root2, file_ext2 = os.path.splitext(os.path.basename(header_file2.include_path))

                if file_root1 == file_root2 and file_ext1 != file_ext2:
                    if header_file1.component and header_file2.component:
                        if header_file1.component == header_file2.component:
                            # print('Cycle detected')
                            pass

                    elif header_file1.component and not header_file2.component:
                        pass

                    elif not header_file1.component and header_file2.component:
                        pass

                    else:
                        component = Component(header_file1, header_file2)
                        self.components.append(component)
                        self.header_files.remove(header_file1)
                        self.header_files.remove(header_file2)

    def render_graph(self, outfile):
        env = Environment(
            loader=FileSystemLoader('/home/sascha/projects/cppdep'),
            trim_blocks=True,
            lstrip_blocks=True
        )
        graph_template = env.get_template('graph.j2')
        graph_template.stream(self.__dict__).dump(outfile)
        print(outfile + ' has been written')

def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--include-dir', action='append', default=list())
    parser.add_argument('-s', '--source-dir', action='append', default=list())
    parser.add_argument('-d', '--macro', action='append', default=list())
    parser.add_argument('-o', '--outfile', nargs=1, default=['graph.dot'])
    return parser.parse_args()

def to_dict(obj):
    return json.loads(json.dumps(obj, default=vars))

def main():
    args = parse_arguments()
    project = Project()
    project.scan_include_dirs(args.include_dir)
    project.scan_source_dirs(args.source_dir)
    project.preprocess_header_files(args.macro)
    project.preprocess_source_files(args.macro)
    project.transitive_reduction()
    project.component_partitioning()
    project.render_graph(args.outfile[0])
    return 0

if __name__ == '__main__':
    sys.exit(main())
