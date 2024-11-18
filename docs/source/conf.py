# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
import subprocess
import site

# Add site-packages path to sys.path
docs_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(docs_dir, "../../"))
sys.path.insert(0, os.path.join(repo_root, "suave_sql"))
sys.path.insert(0, os.path.join(repo_root, "tests"))

print("Current working directory:", os.getcwd())
print("sys.path:")
for path in sys.path:
    print(path)

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'suave_sql'
copyright = '2024, eli'
author = 'eli'
release = '0.0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ['sphinx.ext.napoleon',
'sphinx.ext.autodoc', 
'sphinx.ext.autosectionlabel',
"myst_nb",
'sphinx.ext.githubpages']

templates_path = ['_templates']
exclude_patterns = []



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_book_theme'
#html_static_path = ['_static']
html_theme_options = {
    "show_navbar_depth": 4,
    "max_navbar_depth": 6,
    "show_toc_level": 2
}


html_sidebars = {
    "**": ["sbt-sidebar-nav.html"]
}

autodoc_default_options = {
    'member-order': 'bysource',
    'show-inheritance': False
}

toc_object_entries_show_parents = 'hide'

autosectionlabel_prefix_document = True

jupyter_execute_notebooks = "auto"  # Ensure this is correct
nb_execution_mode = "auto"         # Default execution mode


def skip(app, what, name, obj, would_skip, options):
    if name == "__init__":
        return False
    return would_skip



# table time
def run_table_generation(app):
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "generate_table.py"))
    subprocess.run(["python", script_path], check=True)

def setup(app):
    app.connect("autodoc-skip-member", skip)
    app.connect("builder-inited", run_table_generation)