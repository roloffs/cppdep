# cppdep

This project aims to automatically analyze the dependency structure of c++ projects.
It does not depend on any specific project layout, instead it basically walks through the project structure based on your input and finds c++ source and header files, which are related to each other via include directives.
After source code analysis, component analysis according to Lakos'96 component's definition is done.
This definition just says that a c++ component is the combination of a `.cpp` file and a `.h` file having the same name.
After component analysis, dependencies are cleaned up by applying transitive reduction to the resulting dependency graph.
Finally a dot graph file is generated, which can be used to generate a `.svg` file, a `.png` file, or similar.

# Install dependencies

```bash
pip install -r requirements.txt
```

# Invocation

## Simple project structure

If your project has the following structure:

```
project
\-- src
|   \-- *.cpp
|
\-- include
    \-- *.hpp
```

Then you can call the following command from the top-level project directory:

```bash
cppdep.py -I include -S src
```

After successful execution, a `graph.dot` file in the current working directory has been generated.

This can be translated to a `.svg` file using the following command:

```bash
dot -Tsvg graph.dot -o graph.svg
```

## Complex project structure

If you have different components that internally follow the naming convention to use `src` for source files and `include` for include files, then you can call the following command from the top-level project directory:

```bash
cppdep.py `find -name include -exec echo -I {} \;` `find -name src -exec echo -S {} \;`
```
