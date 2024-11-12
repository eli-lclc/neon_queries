import pandas as pd

import random
import pyperclip
import xlsxwriter
from collections import OrderedDict
from datetime import timedelta
from functools import reduce

import os
import sys 
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_funcs

class Report:
    def __init__ (self, report_functions, engine_settings, start_date, end_date, report_type = 'Queries', interval = None, group_by_interval = False):
        '''
        Creates an object that runs a report and stores its outputs

        Parameters:
            report_functions (Dict): A dictionary of functions to run. Value is 
            engine_settings (Dict): A dictionary of preferences to initialize a suave_sql object
            start_date (Str): The start date of the report period, formatted as 'YYYY-MM-DD'
            end_date (Str): The end date of the report period, formatted as 'YYYY-MM-DD'
            report_type: The sql_funcs object to use. Options include Audits, IDHS, ReferralAsks, Queries. Defaults to Queries
            interval: (optional) The date intervals within the time period to run the report over. 'MS' for month, '3MS' for quarter, 'YS' for year. Defaults to None
            group_by_interval (Bool): (optional) True groups a series of reports by time interval, False groups by each query. Defaults to False

        Examples:
            Sample report_functions::
                
                funcz = {"highest cases by team": ("highest_cases", (False,)),
                        "highest cases by atty": ("highest_cases", (True,)),
                        "all client neighborhoods":("dem_address",(False, 'region',)),
                        "custody status counts":("custody_status",(True,)),
                        "services missing staff":("service_lacks_staff",())
                            }
            
            Sample engine settings::

                engine = create_engine('mysql+pymysql://eli:password@LCLCN001/neon', isolation_level="AUTOCOMMIT")
                full_engine_settings = {
                    'engine': engine,
                    'print_SQL': True,
                    'clipboard': False,
                    'mycase': True,
                    'default_table': 'stints.neon_chd'
                }

            Create a report for all clients between January and August::

                r = Report(funcz, full_engine_settings, '2024-01-01', '2024-08-31', interval = None, report_type = 'Queries')
            
            See reports for each month between January and August side-by-side::

                r = Report(funcz, full_engine_settings, '2024-01-01', '2024-08-31', report_type = 'Queries', interval = 'MS')
            
            See reports for each quarter between January and August one at a time::

                r = Report(funcz, full_engine_settings, '2024-01-01', '2024-08-31', report_type = 'Queries', interval = '3MS', group_by_interval = True)
        '''
        self.report_functions = report_functions
        self.engine_settings = engine_settings
        self.start_date = start_date
        self.end_date = end_date
        self.report_type = report_type
        if not interval:
            self.run_a_report()
        else:
            self.group_by_interval = group_by_interval
            self.date_dict = self.make_date_dict(interval)
            self.generate_reports()

    def run_a_report(self):
        '''
        Runs the report using sql_funcs' Tables.run_report() and saves it as a dictionary. Done automatically when using the Report object.

        Example:
            To access the full dictionary of outputs::

                r.report_outputs

            To access a single query::

                r.report_outputs["all client neighborhoods"]
        '''
        full_inputs = {**{'t1':self.start_date, 't2':self.end_date}, **self.engine_settings}
        classtype = getattr(sql_funcs, self.report_type)
        q = classtype(**full_inputs)

        if isinstance(next(iter(self.report_functions.values())),dict):
            self.report_outputs = {}
            for sheet, queries in self.report_functions.items():
                self.report_outputs[sheet] = q.run_report(func_dict = queries)
        else:
            self.report_outputs = q.run_report(func_dict=self.report_functions)

    def report_to_excel(self, file_path, query_tabs = False, spacer_rows = 1):

        '''
        Saves the report outputs to an excel file

        Parameters:
            file_path: The new file path for the excel document
            query_tabs (Bool): Whether each function should get its own tab in the file. Must be False if report_functions has multiple levels. Defaults to False
            spacer_rows (Int): The number of empty rows to put between each query if not on separate tabs. Defaults to 1

        Examples:
            Save each query on separate tabs::

                r.report_to_excel(file_path="C:/Users/eli/Downloads/test.xlsx", query_tabs=True)
            
            Put two spaces between each query on the same sheet::
                
                r.report_to_excel(file_path="C:/Users/eli/Downloads/test.xlsx", spaces = True)
        '''

        def format_sheet(query_dict, sheet_name = 'Sheet1', spacer_rows = spacer_rows):
            empty.to_excel(writer,sheet_name=sheet_name, startrow=0 , startcol=0, index=False)
            worksheet = writer.sheets[sheet_name]
            worksheet.set_column('A:Z', 15, standard_format)
            row = 1
            for query_name, query_df in query_dict.items():
                column_levels = query_df.columns.nlevels
                if column_levels > 1:
                    query_df = query_df.reset_index()
                    query_df.iloc[1: , :].to_excel(writer,sheet_name=sheet_name,startrow=row , startcol=-1)
                    df_spacer_rows = column_levels + spacer_rows - 1 #same space bt multiindex dfs & regulars
                else:
                    query_df.to_excel(writer,sheet_name=sheet_name,startrow=row , startcol=0, index=False)
                    df_spacer_rows = spacer_rows
                
                #index columns
                nonnum_cols = [idx for idx, col in enumerate(query_df.select_dtypes(exclude=['number']).columns)]
                if nonnum_cols:
                    worksheet.conditional_format(row + column_levels, 0, row + query_df.shape[0] + column_levels - 1, max(nonnum_cols), 
                    {'type':'no_errors', 'format':index_format})
                # table title
                worksheet.merge_range(row-1, 0, row-1, (query_df.shape[1])-1, query_name.upper(), chart_title_format)
                row = row + len(query_df.index) + df_spacer_rows + 3
        
        def format_tabs(query_dict):
            for query_name, query_df in query_dict.items():
                empty.to_excel(writer,sheet_name=query_name,startrow=0 , startcol=0, index=False)
                worksheet = writer.sheets[query_name]
                worksheet.set_column('A:Z', 15, standard_format)

                column_levels = query_df.columns.nlevels
                if column_levels > 1:
                    query_df = query_df.reset_index()
                    query_df.iloc[1: , :].to_excel(writer,sheet_name=query_name,startrow=1 , startcol=-1)
                else:
                    query_df.to_excel(writer,sheet_name=query_name,startrow=1 , startcol=0, index=False)
                #index columns
                nonnum_cols = [idx for idx, col in enumerate(query_df.select_dtypes(exclude=['number']).columns)]
                worksheet.conditional_format(column_levels + 1, 0, query_df.shape[0] + column_levels, max(nonnum_cols),
                {'type':'no_errors', 'format':index_format})
                #chart title
                worksheet.merge_range(0, 0, 0, (query_df.shape[1])-1, query_name.upper(), chart_title_format)

        writer = pd.ExcelWriter(file_path, engine='xlsxwriter')
        workbook = writer.book

        #format time
        standard_format = workbook.add_format()
        standard_format.set_text_wrap()

        chart_title_format = workbook.add_format({'align': 'center'})
        chart_title_format.set_underline()

        index_format = workbook.add_format()
        index_format.set_italic()
        index_format.set_bg_color('#D7D7D7')
        index_format.set_border(1)

        empty = pd.DataFrame()

        # check if data is nested 
        random_key = random.choice(list(self.report_outputs.keys()))
        if isinstance(self.report_outputs[random_key], dict):
            for key, data_dict in self.report_outputs.items():
                format_sheet(data_dict, key)
        #cool it isnt
        else:
            if query_tabs:
                format_tabs(self.report_outputs)
            else:
                format_sheet(self.report_outputs)
        writer.close()

    def make_date_dict(self, interval):
        '''
        Makes a dictionary of dates to pass to an sql_funcs object

        Parameters:
            interval: the time interval to subset the dates. "MS" for month, "3MS" for quarter, "YS" for year
        '''

        quarters = {'January': 'Q1',
        'April':'Q2',
        'July':'Q3',
        'October':'Q4'}

        date_range = pd.date_range(start=self.start_date, end=self.end_date, freq=interval)
        date_tally = 0

        date_dict = {}
        for date in date_range:
            date_tally = date_tally + 1

            range_start = date.strftime('%Y-%m-%d')
            if len(date_range) == date_tally:
                range_end = pd.to_datetime(self.end_date).strftime('%Y-%m-%d')
            else:
                range_end = (date_range[date_tally] - timedelta(days=1)).strftime('%Y-%m-%d')
            month_name = date.month_name()
            if interval == 'YS':
                range_name = f'{date.year}'
            elif interval == '3MS':
                range_name = f'{quarters[month_name]} {date.year}'
            else:
                range_name = f'{month_name} {date.year}'
            date_dict[range_name] = {'t1': range_start, 't2':range_end}
        self.date_dict = date_dict
        return date_dict
    
    def generate_reports(self):
        '''
        Generates reports for each time interval within the report and saves them to self.report_outputs.
    
        '''
        report_outputs = {key: OrderedDict() for key in self.report_functions} if not self.group_by_interval else {key: OrderedDict() for key in self.date_dict}
        for date_key, first_two_inputs in self.date_dict.items():
            full_inputs = {**first_two_inputs, **self.engine_settings}
            
            classtype = getattr(sql_funcs, self.report_type)
            q = classtype(**full_inputs)
            interval_report = q.run_report(func_dict=self.report_functions)
            
            for func_name, func_df in interval_report.items():
                if self.group_by_interval:
                    report_outputs[date_key][func_name] = func_df
                else:
                    report_outputs[func_name][date_key] = func_df
        if self.group_by_interval:
            self.report_outputs = report_outputs
        else:
            self.report_outputs = self.consolidate_query_outputs(report_outputs)
        return report_outputs



    def consolidate_query_outputs(self, query_dict):
        '''
        Consolidates outputs for a given query over multiple intervals into one df

        Parameters:
            query_dict: the dictionary of report outputs
        '''
        
        def one_row(query_dict):
            df_list = []
            for key, df in query_dict.items():
                df.index = [key] * len(df)
                df = df.T
                df = df.reset_index()
                df_list.append(df)
            merged_df = reduce(lambda x, y: x.merge(y, on='index'), df_list)
            return merged_df
        
        def one_numeric(query_dict, indices, numeric_cols):
            df_list = [df.rename(columns={numeric_cols[0]: key}) for key, df in query_dict.items()]
            merged_df = reduce(lambda x, y: x.merge(y, on=indices, how='outer'), df_list)
            return merged_df
        
        def many_numeric(query_dict, indices, numeric_cols):
            dfs_with_multiindex = {key: df.copy() for key, df in query_dict.items()}
            for key in dfs_with_multiindex:
                df = dfs_with_multiindex[key]
                dfs_with_multiindex[key] = df.set_index(indices)
                dfs_with_multiindex[key].columns = pd.MultiIndex.from_product([[key], numeric_cols])

            merged_df = pd.concat(dfs_with_multiindex.values(), axis=1)
            return merged_df
        
        output_dict = {}
        for query_name, query_dict in query_dict.items():
            random_key = random.choice(list(query_dict.keys()))
            random_df = query_dict[random_key]
            if len(random_df) == 1:
                out_df = one_row(query_dict)
            else:
                indices = random_df.select_dtypes(exclude=['number']).columns.tolist()
                numeric_cols = random_df.select_dtypes(include=['number']).columns.tolist()
                if len(numeric_cols) == 1:
                    out_df = one_numeric(query_dict, indices, numeric_cols)
                else:
                    out_df = many_numeric(query_dict, indices, numeric_cols)
            
            output_dict[query_name] = out_df
        return output_dict


