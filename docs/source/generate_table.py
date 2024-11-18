import inspect
import re
from unittest.mock import MagicMock
import os
import sys
import importlib
import inspect
import csv
import pandas as pd

sys.path.insert(0, os.path.abspath('../../suave_sql'))

if __name__ == "__main__":
    # Add paths if running outside of Sphinx
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '../../suave_sql')))
    sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '../../tests')))

sys.modules["sqlalchemy"] = MagicMock()
sys.modules["pyperclip"] = MagicMock()

from suave_sql.sql_funcs import Queries


import os

category_dict = {
    'assess': 'Assessments',
    'custody': 'Custody Statuses',
    'dem': 'Demographics',
    'enrollment': 'Client Enrollment',
    'incident': 'Critical Incidents',
    'isp': 'ISPs',
    'legal': 'Legal',
    'linkages':'Linkages',
    'outreach': 'Outreach Assessments',
    'session':'Case Sessions'
}

def extract_category(string):
    '''
    group queries by category
    '''
    str_cat = string.split('_')[0]
    category = category_dict[str_cat]
    return category


def extract_examples():
    """Extract 'Examples' sections from the docstrings of class methods."""
    examples = []
    
    for name, method in inspect.getmembers(Queries, predicate=inspect.isfunction):
        docstring = inspect.getdoc(method)
        
        if docstring:
            for section in ['Examples:', 'Example:']:
                if section in docstring:
                    # Split the docstring at the section
                    examples_section = docstring.split(section)[1].strip()
                    
                    # Process examples in the section
                    lines = examples_section.splitlines()
                    
                    current_description = None
                    current_function = []
                    reference_name = f''':mod:`{name} <sql_funcs.Queries.{name}>`'''
                    category_name = extract_category(name)
                    
                    for line in lines:
                        line = line.strip()
                        if line.endswith("::"):  # Line indicates a new example
                            # Save the current example if we have data
                            if current_description and current_function:
                                examples.append(
                                    (category_name, current_description, "\n".join(current_function).strip(), reference_name)
                                )
                            # Start a new example
                            current_description = line[:-2].strip()
                            current_function = []
                        else:
                            # Collect lines for the function code
                            current_function.append(line)
                    
                    # Save the last example if it exists
                    if current_description and current_function:
                        examples.append(
                            (category_name, current_description, "\n".join(current_function).strip(), reference_name)
                        )

    return examples

def save_to_csv(examples, filename="examples_table.csv"):
    """Convert extracted examples to a DataFrame and save it as a CSV file."""
    # Create a DataFrame from the examples list
    df = pd.DataFrame(examples, columns=["Category", "I want to...", "Function", "Documentation"])

    # Define the output path to save the CSV in the same directory as the script
    output_path = os.path.join(os.path.dirname(__file__), filename)
    print('saved table', output_path)
    # Save the DataFrame to a CSV file
    df.to_csv(output_path, index=False, encoding='utf-8')
    print('saved table', output_path)

def generate_table():
    """Extract examples and save them as a CSV file."""
    examples = extract_examples()
    if examples:
        save_to_csv(examples)
    else:
        print("No examples found.")

if __name__ == "__main__":
    generate_table()
print('table generated')