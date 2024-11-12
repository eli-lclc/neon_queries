import pandas as pd
import os
from sqlalchemy import create_engine, text, types, bindparam
import re
import pyperclip
from datetime import datetime, timedelta
from functools import wraps

def clipboard_decorator(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        
        if isinstance(result, pd.DataFrame) and self.clipboard:
            result.to_clipboard(index=False)
        return result
    return wrapper

class Tables: 
    def __init__ (self, t1, t2, engine, print_SQL = True, 
    clipboard = False, default_table = "stints.neon", mycase = True):
        '''
        establishes settings and runs stints for the desired time period

        Parameters: 
            t1: start date, formatted as "YYYY-MM-DD"
            t2: end date, formatted as "YYYY-MM-DD"
            print_sql(Bool): whether to print the SQL statements when run, defaults to True
            clipboard(Bool): whether to copy the output table to your clipboard, defaults to False
            default_table: the source table to run queries on. defaults to "stints.neon"
            mycase(Bool): whether the user has a formatted MyCase SQL database, defaults to True


        '''
        self.engine = engine
        self.t1 = t1
        self.t2 = t2
        self.q_t1 = f"'{self.t1}'"
        self.q_t2 = f"'{self.t2}'"
        self.table = default_table
        self.mycase = mycase

        self.print_SQL = print_SQL
        self.clipboard = clipboard
        
        self.con = self.engine.connect().execution_options(autocommit=True)
        self.stints_run()

    def query_run(self, query):
        '''
        runs an SQL query (without a semicolon)
        format for a custom query: query_run(f"""query""")
        
        Parameters:
            query: SQL query
        '''
        query = text(f"{query};")
        if self.print_SQL is True:
            print(query)
        result = self.con.execute(query)
        data = result.fetchall()
        column_names = result.keys()
        df = pd.DataFrame(data, columns=column_names)
        if self.clipboard is True:
            df.to_clipboard(index=False)
        return df
    
    def query_modify(self, original_query, modification):
        '''
        edit a base SQL query, not particularly useful on its own

        Parameters:
            original_query: base SQL query
            modification: string to modify it
        '''
        # Use regular expressions to find the GROUP BY clause
        match = (re.compile(r"(?i)(\bGROUP\s+BY\b)",  re.IGNORECASE)).search(original_query)
        
        if match:
            # Insert the condition before the GROUP BY clause
            modified_query = original_query[:match.start()] + modification + ' ' + original_query[match.start():]
        else:
            # If no GROUP BY clause is found, just append the condition to the end of the query
            modified_query = original_query + ' ' + modification
        return modified_query


    def stints_run(self):
        '''
        runs the stints code
        '''
        stints_statements = f'''
        drop table if exists neon.big_psg;
create table neon.big_psg as (
with prog as (select participant_id, program_id, program_type, program_status, program_start, program_end from neon.programs),
serv as (select program_id, service_type, service_status, service_start, service_end, service_id from neon.services),
gran as (select service_id, grant_type, grant_start, grant_end from neon.psg
join (select service_id, max(grant_id) as grant_id from neon.psg
group by service_id) serv using(service_id, grant_id))
select participant_id, program_type, program_start, program_end, service_type, service_start, service_end, grant_type, grant_start, grant_end 
from prog
left join serv using(program_id)
left join gran using(service_id));

drop table if exists stints.neon;
create table stints.neon as(
select first_name, last_name, participant_id, program_type, program_start, program_end,
service_type, service_start, service_end, grant_type, grant_start, grant_end,
gender, race, age, birth_date, language_primary, case_managers, outreach_workers, attorneys from neon.big_psg
join neon.basic_info using(participant_id)
where ((program_start is null or program_start <= {self.q_t2}) and (program_end is null or program_end >= {self.q_t1})) and 
(service_start is null or service_start <= {self.q_t2}) and (service_end is null or service_end >= {self.q_t1}) and 
(grant_start is null or grant_start <= {self.q_t2})  and (grant_end is null or grant_end >= {self.q_t1}));

drop table if exists stints.neon_chd;
create table stints.neon_chd as(select * from stints.neon
where program_type regexp 'chd|community navigation');

drop table if exists neon.client_teams;
create table neon.client_teams as
with active_services as(
select participant_id, first_name, last_name, service_type from {self.table}
where program_end is null and service_end is null),

all_staff as(
select participant_id, service_type, full_name as staff_name, team
from (select participant_id, full_name, 
case when a.staff_type like 'outreach%' then 'outreach'
when a.staff_type like 'case%' then 'case management'
when a.staff_type like '%attorney%' then 'legal'
end as 'service_type', team
from neon.assigned_staff a
left join neon.staff_ref r using(full_name)
where staff_end_date is null and staff_active='yes') e),

big_table as(
select * from active_services
left join all_staff using(participant_id, service_type)),

service_counts as (select participant_id, count(distinct service_type) as service_count
from big_table
where service_type not like 'therapy' and team is not null
group by participant_id),
team_counts as(select participant_id, team, count(team) as team_count from big_table
where team is not null
group by participant_id, team),

wide_teams as (select * from
(select distinct n.participant_id, n.first_name, n.last_name, case_managers, cm.team as cm_team, outreach_workers, ow.team as ow_team, attorneys, a.team as leg_team from 
(select * from 
{self.table} where program_end is null and service_end is null) n
left join neon.staff_ref cm on n.case_managers = cm.full_name
left join neon.staff_ref a on n.attorneys = a.full_name
left join neon.staff_ref ow on n.outreach_workers = ow.full_name) a),

better_teams as (
select participant_id, team as participant_team from (
select participant_id, count(distinct service_type) as team_service_count from big_table
where team is not null
group by participant_id
) s
join team_counts using(participant_id)
where team_service_count <= team_count)

select * from wide_teams
left join better_teams using(participant_id)
;

drop table if exists neon.cm_summary;
create table neon.cm_summary as(
with PARTS as 
(select first_name, last_name, participant_id, service_start as cm_start, case_managers as case_manager from stints.neon_chd
where service_type = 'case management' and service_end is null),
ISP as (select participant_id, isp_start, latest_update as isp_update from neon.isp_tracker),
LINKS as(
select participant_id, max(linked_date) as latest_linkage, count(distinct linkage_id) as linkage_count
from
(select * from neon.linkages
join parts using(participant_id)
where (linked_date >=cm_start or start_date >= cm_start) and client_initiated = 'no') l
group by participant_id),
SESSIONS as(
select participant_id, max(case when successful_contact = "Yes" then session_date else null end) as latest_session, 
count(case when successful_contact = "Yes" then session_date else null end) as total_sessions, 
max(session_date) as latest_attempt, count(session_date) as total_attempts
from neon.case_sessions
join parts using(participant_id)
where session_date >= cm_start and contact_type = 'Case Management'
group by participant_id)

select * from parts
left join links using(participant_id)
left join isp using(participant_id)
left join sessions using(participant_id))
;

drop table if exists assess.outreach_tracker;
create table assess.outreach_tracker as(
with parts as (select participant_id, first_name, last_name, outreach_workers outreach_worker, service_start outreach_start from stints.neon_chd
where service_type like 'Outreach' and service_end is null),
eligibility as (select participant_id, count(distinct assessment_date) as elig_count, max(assessment_date) as latest_elig from assess.outreach_eligibility
group by participant_id),
assessment as (
select participant_id, count(distinct assessment_date) assessment_count, max(assessment_date) as latest_assessment from assess.safety_assessment
group by participant_id),
interv as(
select participant_id, count(distinct assessment_date) intervention_count, max(assessment_date) as latest_intervention
from assess.safety_intervention
group by participant_id),
intervention as(
select participant_id, intervention_count, latest_intervention, time_of_intervention from interv
join (select participant_id, time_of_assessment time_of_intervention, assessment_date latest_intervention
from assess.safety_intervention) i using(participant_id, latest_intervention))
select * from parts
left join eligibility using(participant_id)
left join assessment using(participant_id)
left join intervention using(participant_id)
order by outreach_start desc);

        '''
        if self.mycase == True:
            stints_statements = stints_statements + ' ' + f'''drop table if exists neon.legal_mycase;
            create table neon.legal_mycase as(
            with part as (select participant_id, program_start, program_end from neon.programs
            join(select participant_id, count(distinct program_start) as stint_count
            from neon.programs
            where program_type = 'chd'
            group by participant_id) sss using(participant_id)
            where program_type = 'CHD'),

            stinted as(
            select * from part
            join mycase.cases using(participant_id)
            where ((datediff(case_start, program_start) is null or datediff(case_start, program_start) >-60) and (case_end is null or case_end > program_start)and (program_end is null or program_end > case_start)))

            , 
            base as (
            select participant_id, legal_id, mycase_id, sc.case_id, mycase_name, 
            case when case_start is null then arrest_date else case_start end as case_start, 
            case_end, case_status, case_type, violent, juvenile_adult, 
            case when class_prior_to_trial_plea like "fel%" then 'Felony'
            when class_prior_to_trial_plea like "mis%" then 'Misdemeanor'
            else 'Missing' end as class_type,
            class_prior_to_trial_plea, class_after_trial_plea, 
            case_outcome, case_outcome_date, sentence, probation_type, probation_requirements, sentence_length,
            expungable_sealable, expunge_seal_elig_date, expunge_seal_date, was_sentence_reduced, reduction_explain, case_entered_date, outcome_entered_date,
            go_to_trial, program_start
            from stinted sc 
            left join neon.legal using(participant_id, legal_id)
            where (mycase_name not like "%traffic%" and sc.case_id not like '%tr%')),

            fel_rankings as (
            select distinct(mycase_id), fel_reduction from(
            select ranked.*, case when prior_rank < post_rank then 'reduced'
            when prior_rank > post_rank then 'increased'  
            when prior_rank = post_rank then 'remained'
            when prior_rank is not null and post_rank is null then 'missing post'
            else 'missing' end as fel_reduction
            from 
            (select mycase_id, class_prior_to_trial_plea, class_after_trial_plea, prior_rank ,ranking as post_rank from 
            (select mycase_id, class_prior_to_trial_plea, class_after_trial_plea, ranking as prior_rank from 
            (select distinct(mycase_id), class_prior_to_trial_plea, class_after_trial_plea from base) b
            left join misc.felony_classes f1 on b.class_prior_to_trial_plea = f1.felony) prior
            left join misc.felony_classes f2 on prior.class_after_trial_plea = f2.felony) ranked) reduced)
            
            select * from base
            join fel_rankings using(mycase_id));'''
        
        ### update teams




        for statement in stints_statements.split(';'):
            if statement.strip():
                self.con.execute(text(statement.strip() + ';'))
    def run_report(self, func_dict,*args, **kwargs):
        '''
        runs a desired report
        Parameters:
            func_dict: dictionary of functions to include, defaults to self.report_funcs. To use a different  
        '''       
        result_dict = {}
        for result_key, (func_name, func_args) in func_dict.items():
            func = getattr(self, func_name, None)
            if func and callable(func):
                try:
                    # Call the function with func_args and additional args/kwargs
                    result = func(*func_args, *args, **kwargs)
                    result_dict[result_key] = result
                except Exception as e:
                    result_dict[result_key] = f"Error: {str(e)}"
        '''
        fuck you fuck you fuck you

        clipboard_content = []
        for df_name, df in result_dict.items():
            df_content = df.to_csv(index=False, sep='\t')
            content_with_name = f"{df_name}\n{df_content}\n\n"
            clipboard_content.append(content_with_name)

        all_content = "\n".join(clipboard_content)
        pyperclip.copy(all_content)
        '''

        return result_dict
    
    def table_update(self, desired_table, update_default_table = False):
        if desired_table.lower() == 'idhs':
            new_table = 'participants.idhs'
            statements = f'''
            drop table if exists {new_table};
            create table {new_table} as(
            select *, case when grant_start between {self.q_t1} and {self.q_t2} then 'new' else 'continuing' end as new_client,
            case when program_end is not null then 'program'
            when service_end is not null or grant_end is not null then 'service'
            else null end as discharged_client
            from stints.neon
            where grant_type = 'IDHS VP')
            '''
        if desired_table.lower() == 'rjcc':
            new_table = 'stints.rjcc'
            statements = f'''
            drop table if exists {new_table};
            create table {new_table} as(
            with mc as (
            select participant_id, mycase_id, mycase_name from mycase.case_stages
            where stage like "rjcc" and (stage_end is null or stage_end between {self.q_t1} and {self.q_t2}) and stage_start < {self.q_t2}),
            mcc as (select distinct mycase_id from mc
            join neon.legal_mycase using(participant_id, mycase_id, mycase_name)),

            mcunion as (
            select distinct mycase_id from (
            select distinct mycase_id from neon.legal_mycase
            where case_outcome like "%diverted%" or case_status like "%divers%"
            union all 
            select * from mcc) s),

            mccases as(
            select * from mcunion
            join neon.legal_mycase using(mycase_id)),
            mcparts as(
            select distinct(participant_id) from mccases)

            select * from mcparts
            join (select * from stints.neon
            join (select participant_id, count(distinct program_type) program_count
            from stints.neon
            group by participant_id) pc using(participant_id)) s using(participant_id)
            where program_type = 'rjcc' or program_count = 1);
            '''
        for statement in statements.split(';'):
            if statement.strip():
                self.con.execute(text(statement.strip() + ';'))
        if update_default_table is True:
            self.table = new_table


class Audits(Tables):
    def __init__(self, t1, t2, engine, print_SQL = True, clipboard = False, default_table="stints.neon", mycase = True):
        super().__init__(t1, t2, engine, print_SQL, clipboard, default_table, mycase)
        self.stints_run()

    @clipboard_decorator
    def program_lacks_services(self):
        '''
        Returns a table of active programs with no corresponding services.
        '''
        query = f'''
        with psg_table as (
        select * from (select first_name, last_name, participant_id from neon.basic_info) i
        join neon.big_psg using(participant_id)
        left join (select distinct participant_id, case_managers, outreach_workers, attorneys from {self.table}) sn using(participant_id)
        where program_type regexp 'chd|community navigation' and (program_end is null or program_end >= {self.q_t1}) and (service_end is null or service_end  >= {self.q_t1}))

        select * from psg_table where service_type is null
        '''
        df = self.query_run(query)
        return(df)

    @clipboard_decorator
    def service_lacks_grant(self):
        '''
        Returns a table of active services without a corresponding grant.
        '''
        query = f'''with psg_table as (
        select * from (select first_name, last_name, participant_id from neon.basic_info) i
        join neon.big_psg using(participant_id)
        where program_type = 'chd' and (program_end is null or  >= {self.q_t1}) and (service_end is null or service_end  >= {self.q_t1}))

        select * from psg_table where (service_type is not null and grant_type is null) or (service_end is null and grant_end is not null)
        order by participant_id asc'''
        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def service_lacks_staff(self):
        '''
        Returns a table of active services without a corresponding staff member.
        '''

        query = f'''with psg_table as (
        select * from (select first_name, last_name, participant_id from neon.basic_info) i
        join neon.big_psg using(participant_id)
        where program_type = 'chd' and (program_end is null or program_end >= {self.q_t1}) and (service_end is null or service_end >= {self.q_t1})),

        staff as (
        select participant_id, full_name as assigned_staff, case 
            when staff_type = 'case manager' then 'Case Management'
            when staff_type = 'assigned attorney' then 'Legal'
            else 'Outreach' end as 'service_type' 
        from (select distinct(participant_id), first_name, last_name from psg_table) p
        join neon.assigned_staff using(participant_id)
        where staff_active = 'yes')

        select first_name, last_name, service_type, service_start, service_end, assigned_staff from psg_table
        left join staff using (participant_id, service_type)
        where assigned_staff is null and service_type not like 'therapy' and service_end is null
        order by participant_id;
        '''
        df = self.query_run(query)
        return(df)

    @clipboard_decorator
    def staff_lacks_service(self):
        '''
        Returns a table of staff members assigned to clients without a corresponding service type
        '''

        query = f'''with serv as (
        select participant_id, program_type, service_type, service_start, service_end from neon.big_psg
        where service_end is null and program_end is null and service_type is not null),

        concat_serv as (
        select participant_id, group_concat(distinct service_type) as active_services
        from serv
        group by participant_id
        ),

        staf as(
        select participant_id, first_name, last_name, active_services,full_name as staff_name, staff_type, staff_start_date, case 
            when staff_type = 'case manager' then 'Case Management'
            when staff_type = 'assigned attorney' then 'Legal'
            else 'Outreach' end as 'service_type'  from neon.assigned_staff
        join (select first_name, last_name, participant_id from neon.basic_info) n using(participant_id)
        join concat_serv using(participant_id)
        join (select distinct participant_id from serv) s using(participant_id)
        where staff_active = 'Yes')

        select * from staf
        left join serv using(participant_id, service_type)
        where program_type is null;
        '''
        df = self.query_run(query)
        return(df)


class Queries(Audits):
    def __init__(self, t1, t2, engine, print_SQL = True, clipboard = False, default_table="stints.neon", mycase = True):
        super().__init__(t1, t2, engine, print_SQL, clipboard, default_table, mycase)
    '''
    Sets up a table for a given timeframe

    Parameters:
        t1: start date, formatted as "YYYY-MM-DD"
        t2: end date, formatted as "YYYY-MM-DD"
        print_sql (Bool): whether to print the SQL statements when run, defaults to True
        clipboard (Bool): whether to copy the output table to your clipboard, defaults to False
        default_table: the source table to run queries on. defaults to "stints.neon"
    
    '''
    @clipboard_decorator
    def assess_assm(self, cutoff_score = 2, score_date = 'min'):
        '''
        Counts clients with ASSM scores in a certain range.

        Parameters:
            cutoff_score: the upper bound of score to include. Defaults to 2
            score_date (str): 'min' returns the earliest score, 'max' returns the latest. Defaults to 'min'

        Examples:
            Get a count of clients with their earliest ASSM scores between 1-2::

                e.assess_assm()

            Get a count of clients with their latest ASSM scores between 1-3::
                
                e.assess_assm(cutoff_score=3, score_date='max')

        '''

        query = f'''
        with elig_assess as(
        select * from assess.assm
        join (select distinct participant_id, program_start from {self.table}
        where program_type regexp ".*CHD.*|.*Navigation.*") n using(participant_id)
        where assessment_date >= program_start),

        main_assm as(select * from elig_assess
        join (select distinct participant_id, {score_date}(assessment_date) assessment_date from elig_assess group by participant_id) e using (participant_id, assessment_date))

        select 'crisis_scores' as domain,
        count(distinct case when edu_adult between 1 and {cutoff_score} or edu_juv between 1 and {cutoff_score} then participant_id else null end) as edu,
        count(distinct case when employment between 1 and {cutoff_score} then participant_id else null end) as employment,
        count(distinct case when family_relations between 1 and {cutoff_score} then participant_id else null end) as family_relations,
        count(distinct case when peer_relations between 1 and {cutoff_score} then participant_id else null end) as peer_relations,
        count(distinct case when legal between 1 and {cutoff_score} then participant_id else null end) as legal,
        count(distinct case when community_involvement between 1 and {cutoff_score} then participant_id else null end) as community_involvement,
        count(distinct case when mental_health between 1 and {cutoff_score} then participant_id else null end) as mental_health,
        count(distinct case when substance_abuse between 1 and {cutoff_score} then participant_id else null end) as substance_abuse,
        count(distinct case when safety between 1 and {cutoff_score} then participant_id else null end) as safety,
        count(distinct case when housing between 1 and {cutoff_score} then participant_id else null end) as housing,
        count(distinct case when food between 1 and {cutoff_score} then participant_id else null end) as food,
        count(distinct case when life_skills between 1 and {cutoff_score} then participant_id else null end) as life_skills,
        count(distinct case when mobility between 1 and {cutoff_score} then participant_id else null end) as mobility
        from main_assm
        UNION ALL
        select 'total_participants' as domain,
        count(distinct case when edu_adult is not null or edu_juv is not null then participant_id else null end) as edu,
        count(distinct case when employment is not null then participant_id else null end) as employment,
        count(distinct case when family_relations is not null then participant_id else null end) as family_relations,
        count(distinct case when peer_relations is not null then participant_id else null end) as peer_relations,
        count(distinct case when legal is not null then participant_id else null end) as legal,
        count(distinct case when community_involvement is not null then participant_id else null end) as community_involvement,
        count(distinct case when mental_health is not null then participant_id else null end) as mental_health,
        count(distinct case when substance_abuse is not null then participant_id else null end) as substance_abuse,
        count(distinct case when safety is not null then participant_id else null end) as safety,
        count(distinct case when housing is not null then participant_id else null end) as housing,
        count(distinct case when food is not null then participant_id else null end) as food,
        count(distinct case when life_skills is not null then participant_id else null end) as life_skills,
        count(distinct case when mobility is not null then participant_id else null end) as mobility
        from main_assm;
        '''
        df = self.query_run(query)
        df = df.set_index('domain').T
        print(df)
        df['crisis_percentage'] = df['crisis_scores']/df['total_participants']
        df = df.reset_index().sort_values(by=['crisis_percentage'], ascending=False)
        return(df)
    
    def assess_missing_outreach(self):
        '''
        Returns a list of outreach clients missing assessments

        Example:
            Get clients missing outreach assessments::
                
                e.assess_missing_outreach
        '''

        query = f'''
        select participant_id, first_name, last_name, outreach_worker, outreach_start from assess.outreach_tracker
        join (select distinct participant_id from stints.neon_chd
        where service_type like 'outreach' and service_end is null) o using(participant_id) 
        where elig_count is null and assessment_count is null and intervention_count is null
        '''
        df = self.query_run(query)
        return(df)


    @clipboard_decorator
    def custody_status(self, summary_table = False):
        '''
        Returns a table of clients' most recent custody statuses

        Parameters:
            summary_table (Bool): groups clients by latest custody status. Defaults to False

        Examples:
            Get a record of each clients' latest custody status::

                e.custody_status()

            Get the number of clients with each custody status::

                e.custody_status(summary_table=True)
        '''
        
        query = f'''
        with parts as (
        select distinct participant_id, first_name, last_name, program_start
        from stints.neon_chd
        where program_type regexp 'chd|community navigation'),
        cust_elig as (select * from parts
        join neon.custody_status using(participant_id)
        where datediff(custody_status_date, program_start) >= -90),
        cust as (
        select participant_id, custody_status, custody_status_date from cust_elig
        join (select participant_id, max(custody_status_id) custody_status_id from cust_elig 
        group by participant_id)  c
        using(participant_id, custody_status_id)),
        cust_table as(
        select participant_id, first_name, last_name, program_start, case when custody_status is null then 'MISSING' else custody_status end as custody_status, custody_status_date from parts
        left join cust using(participant_id))
        '''
        if summary_table:
            addendum = f'''select custody_status, count(distinct participant_id) as num_clients
                            from cust_table
                            group by custody_status'''
        else:
            addendum = f'''select * from cust_table'''

        query = query + ' ' + addendum

        df = self.query_run(query)
        return(df)

    @clipboard_decorator
    def dem_address(self, new_clients = False, group_by = None):
        '''
        returns client address records. 

        Parameters:
            new_clients (bool): include only new clients. Defaults to False
            group_by: group client records, takes 'zip', 'community', 'region'. Defaults to None.
        
        Examples:
            Get a table of each client's address::

                e.dem_address()
            
            Get a count of the number of client's in each neighborhood::
                
                e.dem_address(group_by='community')
            
            Get a count of the number of new clients in each zipcode::

                e.dem_address(new_clients=True, group_by='zip')
        '''
        if new_clients == False: 
            query = f'''
            with ranked_addresses as (select *,
            ROW_NUMBER() OVER (partition by participant_id ORDER BY primary_address DESC, address_id DESC, civicore_address_id asc) AS rn
            from neon.address
            join (select distinct participant_id, first_name, last_name from stints.neon) sn using(participant_id)),
            address_table as(
            select participant_id, first_name, last_name, address1, address2, city, state, zip, primary_address, community
            from ranked_addresses
            where rn = 1)
            '''
        if new_clients == True: 
            query = f'''
            with ranked_addresses as (select *,
            ROW_NUMBER() OVER (partition by participant_id ORDER BY primary_address DESC, address_id DESC, civicore_address_id asc) AS rn
            from neon.address
            join (select distinct participant_id, first_name, last_name from stints.neon
            where program_start between {self.q_t1} and {self.q_t2}) sn using(participant_id)),
            address_table as(
            select participant_id, first_name, last_name, address1, address2, city, state, zip, primary_address, community
            from ranked_addresses
            where rn = 1)
            '''

        if group_by == None:
            modifier = f'''select * from address_table'''
        if group_by == 'region':
            modifier = f'''
                        ,
                        region_table as(
            select participant_id, case when community not regexp ".*garfield park|little village|north lawndale|austin" then region else community end as community
            from address_table
            join misc.chicago_regions using(community))
            
            select community, count(distinct participant_id) count
            from region_table
            group by community
            ORDER BY 
				CASE 
					WHEN community IN ('North Lawndale', 'Austin', 'Little Village', 'East Garfield Park', 'West Garfield Park') THEN 0
					WHEN community = 'Other_Chicago' THEN 2
					ELSE 1
				END,
				community ASC;
            '''
        else:
            modifier = f'''select {group_by}, count(distinct participant_id) as count from address_table
            group by {group_by}'''
        query = self.query_modify(str(query), modifier)
        df = self.query_run(query)
        return(df)
        
    @clipboard_decorator
    def dem_age(self, new_clients = False, age = 18, cutoff_date = "active"):
        '''
        Returns a count of clients below/above a certain age threshold, or identifies clients as juveniles/adults 

        Parameters:
            new_clients (Bool): if true, only counts clients who began between t1 and t2. defaults to False
            tally (Bool): if true, returns a count of juv/adults, if false, returns a list. defaults to True
            age: threshold at which a client is counted as a juvenile. defaults to 18
            cutoff_date: The date to on which to calculate a clients age ("active", "current", and "report_period"). Defaults to "active".

        Examples:
            Get the number of clients currently under 18::

                e.dem_age(age=17, cutoff_date='current')
            
            Get the number of clients under 19 at their time of enrollment::

                e.dem_age(cutoff_date='active')

            Get the number of new clients under 19 at the start of the reporting period::

                e.dem_age(new_clients=True, cutoff_date='report_period')
        '''

        if cutoff_date.lower() == "active":
            age_group = 'active_age_group'
        if cutoff_date.lower() == "current":
            age_group = 'current_age_group'
        if cutoff_date.lower() == "report_period":
            age_group = 'stint_age_group'
        
        query = f'''
        with ages as(
            select *, case when age < {age} then 'juvenile' when age >= {age} then 'adult' else 'missing' end as current_age_group,
            case when active_age < {age} then 'juvenile' when active_age >= {age} then 'adult' else 'missing' end as active_age_group,
            case when stint_age < {age} then 'juvenile' when stint_age >= {age} then 'adult' else 'missing' end as stint_age_group
            from 
            (select *, 
            floor(datediff(program_start, birth_date)/365) as active_age,
            floor(datediff({self.q_t1}, birth_date)/365) as stint_age
            from {self.table})ag)

            select {age_group}, count(distinct participant_id) as count from ages
            group by {age_group};
        '''
        modifier = f'''WHERE program_start between {self.q_t1} AND {self.q_t2}'''
        if new_clients is True:
            query = self.query_modify(str(query), modifier)
        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def dem_race_gender(self, new_clients = False, race_gender = 'race'):
        '''
        Returns a count of client races or genders

        Parameters:
            new_clients (Bool): if true, only counts clients who began between t1 and t2. defaults to False
            race_gender: the category to tally, enter either "race" or "gender". defaults to 'race'

        Examples:
            Get the genders of new clients::

                e.dem_race_gender(new_clients=True, race_gender='gender')

            Get client races::
                
                e.dem_race_gender()
        '''
        query = f'''select {race_gender}, count(distinct participant_id) as count
        from {self.table}
        group by {race_gender}'''
        modifier = f'''WHERE program_start between {self.q_t1} AND {self.q_t2}'''
        if new_clients is True:
            query = self.query_modify(str(query), modifier)  # Use self.query_modify here
        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def enrollment(self, program_type = False, service_type = False, grant_type = False):
        '''
        Returns a count of clients, with options to break down by program, service, and/or grant.

        Parameters:
            program_type(Bool): distinguish by program, defaults to False
            service_type(Bool): distinguish by service, defaults to False
            grant_type(Bool): distinguish by grant, defaults to False

        Examples:
            Get the total number of clients enrolled::

                e.enrollment()

            Get the number of clients enrolled in each program::

                e.enrollment(program_type=True)
            
            Get the number of clients receiving each service for every program::

                e.enrollment(program_type=True, service_type=True)

            Get the number of clients receiving each service on a grant::

                e.enrollment(service_type=True, grant_type=True)
        '''

        types_list = []
        if program_type:
            types_list.append('program_type')
        if service_type:
            types_list.append('service_type')
        if grant_type:
            types_list.append('grant_type')
        if types_list:
            types_str = ', '.join(str(st) for st in types_list)
            query = f'''select {types_str}, count(distinct participant_id) as count
            from {self.table}
            group by {types_str}'''
        else:
            query = f'''select count(distinct participant_id) count
            from {self.table}'''
        df = self.query_run(query)
        return(df)

    def enrollment_bundles(self):
        '''
        Counts clients by their bundle of programs

        Example:
            Get the number of clients enrolled in each combination of programs::
                
                e.enrollment_bundles()
        '''
        query = f'''select prog, count(distinct participant_id) from
        (select participant_id, group_concat(distinct program_type) prog from stints.neon
        group by participant_id) s
        group by prog'''
        df = self.query_run(query)
        return(df)

    def enrollment_flow(self):
        '''
        Counts the flow of clients in and out of LCLC in the timeframe.

        Example:
            Get the number of clients enrolled/unenrolled in the timeframe::

                e.enrollment_flow()
        '''
        
        query = f'''
        with progs as(
        select distinct(program_type), participant_id, first_name, last_name, prog_counts ,program_start, program_end,
        case 
            when program_start between {self.q_t1} AND {self.q_t2} and program_end between {self.q_t1} AND {self.q_t2} then 'started_ended'
            when program_start between {self.q_t1} AND {self.q_t2} then 'started'
            when program_end between {self.q_t1} AND {self.q_t2} then 'ended'
            else null
            end as prog_status
        from {self.table}
        join (select participant_id, count(distinct program_type) prog_counts
        from {self.table}
        group by participant_id) p using(participant_id)),

        status_tally as(
        select participant_id, prog_status, prog_counts, count(prog_status) status_count from progs
        group by participant_id, prog_status, prog_counts),
        stat_tally as (
        select prog_status, count(distinct participant_id) status_count
        from status_tally
        where prog_counts = status_count
        group by prog_status
        order by case when prog_status = 'started' then 1 
        when prog_status = 'started_ended' then 2 else 3 end)

        select * from stat_tally
        union all
        select concat('Close Reason: ', close_reason), count(distinct participant_id) reason_count from status_tally
        join neon.programs using(participant_id)
        where prog_counts = status_count and prog_status like '%ended' and close_reason is not null
        group by close_reason
        '''

        df = self.query_run(query)
        return df
    
    def incident_tally(self):
        '''
        counts incidents in timeframe, distinguishing between CPIC and non-CPIC events.  

        Example:
            Get the number of incidents in the timeframe::

                e.incident_tally()
        '''

        query = f'''SELECT count(case when how_hear regexp '.*CPIC.*' then incident_id else null end) as CPIC,
	count(case when how_hear not regexp '.*CPIC.*' then incident_id else null end) as non_CPIC
    FROM neon.critical_incidents
    where (incident_date between {self.q_t1} and {self.q_t2})'''
        df = self.query_run(query)
        return df

    def incident_response(self):
        '''
        counts incidents responded to in timeframe

        Example:
            Get the number of incident responses in the timeframe::

                e.incident_response()
        '''

        query = f'''select count(incident_id) as total_incidents, 
        count(case when did_staff_respond = 'yes' then incident_id else null end) as responded_incidents 
        from neon.critical_incidents
        where (incident_date between {self.q_t1} and {self.q_t2})'''
        df = self.query_run(query)
        return df
    
    @clipboard_decorator
    def isp_goal_tracker(self):
        '''
        Breaks out client ISP goals by domain and completion

        Example:
            Get the status of client ISP goals by domain::

                e.isp_goal_tracker()
        '''

        query = f'''SELECT goal_domain, count(case when latest_status = 'in progress' then participant_id else null end) as in_progress,
        count(case when latest_status = 'completed' then participant_id else null end) as completed,
        count(case when latest_status = 'discontinued' then participant_id else null end) as discontinued,
        count(case when latest_status = 'Not Yet Started' then participant_id else null end) as not_yet_started FROM neon.isp_status
        join (select distinct participant_id, service_start from {self.table}
        where service_type like 'case management') i using(participant_id)
        group by goal_domain'''
        df = self.query_run(query)
        return df

    @clipboard_decorator
    def isp_tracker(self, just_cm = True, summary_table = False, service_days_cutoff = 45):
        '''
        Returns a table of client service plan statuses or a table summarizing overall plan completion.

        Parameters:
            just_cm (Bool): if true, only looks at clients enrolled in case management. Defaults to True
            summary_table (Bool): whether to return a summary table. Defaults to False
            service_days_cutoff: the day threshold at which a service plan ought to be complete. Defaults to 45 
    
        Examples:
            Get a full table of ISP statuses for all clients::

                e.isp_tracker(just_cm=False)

            Get the count of case management clients missing a service plan after 60 days::

                e.isp_tracker(summary_table=True, service_days_cutoff=60)
        '''

        if just_cm == True:
            prog_serv = 'service'
            base_table = f'''select participant_id, first_name, last_name, datediff({prog_serv}_stop, {prog_serv}_start) as {prog_serv}_days from
            (select participant_id, first_name, last_name, {prog_serv}_start, {prog_serv}_end, case when {prog_serv}_end is null then {self.q_t2} else {prog_serv}_end end as {prog_serv}_stop from {self.table}
            join 
                (select participant_id, {prog_serv}_type, max({prog_serv}_start) as {prog_serv}_start from {self.table}
                where {prog_serv}_type = 'case management' group by participant_id, {prog_serv}_type) st 
            using(participant_id, {prog_serv}_type, {prog_serv}_start)) serv'''
        if just_cm == False:
            prog_serv = 'program'
            base_table = f'''select participant_id, first_name, last_name, datediff({prog_serv}_stop, {prog_serv}_start) as {prog_serv}_days from
            (select distinct participant_id, first_name, last_name, {prog_serv}_start, {prog_serv}_end, case when {prog_serv}_end is null then {self.q_t2} else {prog_serv}_end end as {prog_serv}_stop from {self.table}
            join 
                (select participant_id, max({prog_serv}_start) as {prog_serv}_start from  {self.table}
                group by participant_id, {prog_serv}_type) st 
            using(participant_id, {prog_serv}_start)) serv'''
        
        query_to_modify = f'''
        with base as ({base_table}),
        assms as (select participant_id, assessment_date latest_assm_date, max(sum) as latest_assm_score from assess.assm
            join (select participant_id, max(assessment_date) assessment_date from assess.assm
            group by participant_id) na using(participant_id, assessment_date)
            group by participant_id, assessment_date),
        custody_status as(
            select participant_id, custody_status, custody_status_date from neon.custody_status
            join 
            (select participant_id, max(custody_status_id) as custody_status_id from neon.custody_status
            group by participant_id) ncs using(participant_id, custody_status_id)),
        big_table as(
            select * from base
            left join custody_status using(participant_id)
            left join assms using(participant_id)
            left join neon.isp_tracker using(participant_id))

        '''

        if summary_table == False:
            modifier = '''select * from big_table'''
        
        if summary_table == True:
            modifier = f'''
            ,
            elig as (select *, case when (custody_status = 'In Custody' or {prog_serv}_days <={service_days_cutoff}) or (custody_status is null and {prog_serv}_days <={service_days_cutoff}) then 'optional needs' else 'needs needs' end as eligibility
            from big_table)

            select eligibility, count(distinct participant_id) as total_participants,
            count(case when latest_assm_date is not null and isp_start is not null then participant_id end) as completed_needs,
            count(case when latest_assm_date is not null and isp_start is null then participant_id end) as just_assm,
            count(case when latest_assm_date is null and isp_start is not null then participant_id end) as just_isp,
            count(case when latest_assm_date is null and isp_start is null then participant_id end) as missing_both
            from elig
            group by eligibility

            '''
        query = query_to_modify + ' ' + modifier
        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def isp_discharged(self, missing_names = False):
        '''
        Returns a table of discharged clients' service plan completion and groups percent of goals completed.

        Parameters:
            missing_names (Bool): whether to return a list of the clients missing an ISP. defaults to False
        
        Examples::
            Get the number of discharged clients broken out by % of their service plan completed::

                e.isp_discharged()

            Get a list of discharged clients with no ISPs recorded::

                e.isp_discharged(missing_names=True)

        '''

        query = f'''
        with discharged_isps as(
        select first_name, last_name, participant_id, isp_start, latest_update, total_goals, goals_completed, goals_in_progress, goals_discontinued, 
        goals_unstarted from neon.isp_tracker
        right join (select * from {self.table} where service_type = 'case management' and (service_end is not null or program_end is not null)) o using(participant_id))
        '''

        if missing_names:
            modifier = f'''
            select first_name, last_name from discharged_isps where isp_start is null
            '''
        else:
            modifier = f'''
            ,
        percent_groups as (
        select participant_id, percent_goals_completed, 
        case when percent_goals_completed is null then 'Missing'
            when percent_goals_completed = 0 then '0%'
            when percent_goals_completed > 0 and percent_goals_completed < .5 then '0%-50%'
            when percent_goals_completed > .5 and percent_goals_completed < 1 then '50%-100%'
            else '100%'
            end as percent_group
            from (select participant_id, goals_completed/total_goals as percent_goals_completed
            from discharged_isps) i)
            
            select percent_group percent_complete, count(distinct participant_id) as participants from percent_groups
            group by percent_group
            order by case 
            when percent_group = '100%' then 1
            when percent_group = '50%-100%' then 2
            when percent_group = '0%-50%' then 3
            when percent_group = "0%" then 4
            else 5
            end asc
            '''
        query = query + ' ' + modifier
        df = self.query_run(query)
        return(df)

    @clipboard_decorator
    def legal_bonanza(self, time_period = False, case_stage = None, ranking_method = None, grouping_cols = [], wide_col = None):
        '''
        Flexible function designed to return a table of legal data.


        Parameters:
            time_period (Bool): Whether to look true only looks at cases active in time period
            case_stage (optional): 'started' only looks at cases started in time period, 'ended' looks at cases ended
            ranking method (optional): 'highest_felony' looks at a client's highest pretrial charge, 'highest_outcome' looks at a clients highest outcome. Defaults to "None"
            grouping_cols (str, list): column(s) to use group_by on. The string 'case_outcomes' automatically includes case_outcome, sentence, and probation_type
            wide_col(optional): column to [widen data] on.
        
        Hints:
            group_by column options: case_type, violent, juvenile_adult, class_prior_to_trial_plea, class_after_trial_plea, case_outcome, sentence, probation_type
            wide_col column options: violent, fel_reduction, class_type

        Examples:
            Get client outcomes in the time period::

                e.legal_bonanza(time_period=True, ranking_method='highest_outcome', grouping_cols='case_outcomes')

            Get types of cases begun in time period::

                e.legal_bonanza(time_period=True, case_stage = 'started', grouping_cols='case_type')

            Get case outcomes grouped by violent status::

                e.legal_bonanza(time_period=True, case_stage='ended', grouping_cols='case_outcome', wide_col='violent')
        '''
        
        base_table = f'''with base as (
        select * from neon.legal_mycase
        join (select distinct participant_id from {self.table}) n using(participant_id)'''
        
        if time_period is True:
            # where statement exists
            if case_stage is None:
                addendum = f'''where (case_start is null or case_start <= {self.q_t2}) and (case_outcome_date is null or case_outcome_date >= {self.q_t1}))'''
            elif case_stage.lower() == 'started':
                addendum = f'''where case_start between {self.q_t1} and {self.q_t2})'''
            elif case_stage.lower() == 'ended':
                addendum = f'''where case_outcome_date between {self.q_t1} and {self.q_t2})'''
        if time_period is False:
            addendum = ')'
        
        base_table = base_table + ' ' + addendum

        table_name = 'base'

        if ranking_method:
            ranked_tables = f'''
            , fel_rank as (select *, case when ranking is null then 10 else ranking end better_rank from base b
            left join misc.felony_classes f on b.class_prior_to_trial_plea = f.felony),
            highest_felony as (
            select participant_id, legal_id, mycase_id, mycase_name, case_start, 
            case_end, case_status, case_type, violent, juvenile_adult, class_prior_to_trial_plea, class_after_trial_plea, fel_reduction,
            case_outcome, case_outcome_date, sentence, probation_type, probation_requirements, sentence_length,
            expungable_sealable, expunge_seal_elig_date, expunge_seal_date, was_sentence_reduced, reduction_explain, case_entered_date, outcome_entered_date,
            go_to_trial, program_start from fel_rank
            join 
            (select participant_id, min(better_rank) as better_rank from 
            fel_rank group by participant_id) fr using(participant_id, better_rank)),

            highest_outcome as(
            select b.* from 
            (select legal_id,
            ROW_NUMBER() OVER (partition by participant_id ORDER BY case_rank desc, sentence_rank desc) as rn
            from(
            select l.*, c.ranking as case_rank, s.ranking as sentence_rank from base l
            left join misc.highest_sentence s using(sentence)
            left join misc.highest_case c using(case_outcome)) lcs
            where case_outcome is not null) ranked_outcomes
            join base b using(legal_id)
            where rn = 1)
                '''
            base_table = base_table + " " + ranked_tables 
            table_name = ranking_method
        
        #handle grouping cols
        existing_groups = {'case_outcomes': ['case_outcome', 'sentence', 'probation_type']}
        if isinstance(grouping_cols, str):
            if grouping_cols in existing_groups:
                grouping_cols = existing_groups[grouping_cols]
            else:
                grouping_cols = list(grouping_cols.split(", "))

        # make wide as desired
        if wide_col:
            count_str = f'''count(distinct case when {wide_col} regexp 'Yes|Felony' then mycase_id else null end) as '{wide_col}',
            count(distinct case when {wide_col} regexp 'No|Misdemeanor' then mycase_id else null end) as 'not {wide_col}',
            count(distinct case when {wide_col} is null or {wide_col} like "%missing%" then mycase_id else null end) as "missing"'''
        else:
            count_str = 'count(distinct mycase_id) as count'


        if grouping_cols is None or (isinstance(grouping_cols, list) and not grouping_cols):
            actual_query = f'''select * from {table_name}'''
        else: 
            cols = ', '.join(str(col) for col in grouping_cols)
            actual_query = f'''select {cols}, {count_str}
            from {table_name}
            group by {cols}
            order by {grouping_cols[0]} asc'''

        query = base_table + ' ' + actual_query

        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def legal_rearrested(self, client_level = True):
        '''
        Returns a count of clients who picked up new cases cumulatively and in the timeframe

        Parameters:
            client_level(Bool): True counts the number of clients, False counts the number of total cases. Defaults to True
        
        Examples:
            Get the number of new cases picked up by clients::

                e.legal_rearrested(client_level=False)
            
            Get the number of clients rearrested::

                e.legal_rearrested()
        '''

        distinct = 'distinct ' if client_level else ''
        query = f'''
        with base as (
        select * from neon.legal_mycase
        join (select distinct participant_id from {self.table}) n using(participant_id)
        where (mycase_name not like "%traffic%" and mycase_id != 31580789)),
        rearrests as (
        select b.*, case when case_start between {self.q_t1} and {self.q_t2} then 'Yes' else 'No' end as timeframe from base b
        join 
        (select participant_id, min(case_start) as earliest_start
        from base
        group by participant_id) e using(participant_id)
        where case_start > earliest_start)

        select * from (select count({distinct} participant_id) as total_clients from base) b
        join (select count({distinct} participant_id) as total_rearrested, count({distinct} case when timeframe = 'Yes' then participant_id else null end) as timeframe_rearrested from rearrests) r
        '''
        df = self.query_run(query)
        return(df)

    @clipboard_decorator
    def linkages_edu_employ(self, just_cm = True,first_n_months = None, ongoing = False, age_cutoff = 18, include_wfd = True):
        '''
        Counts the number of clients enrolled/employed by age group. 

        Parameters:
            just_cm (Bool): Whether to only include clients enrolled in case management. Defaults to True
            first_n_months (optional, int): Only counts linkages in the first N months of program enrollment, usually 6 or 9. Defaults to None
            ongoing (Bool): Only include linkages with no end date. Defaults to False
            age_cutoff (int): inclusive upper bound for 'school-aged' clients. Defaults to 18
            include_wfd (Bool): whether to count workforce development linkages as employment. Defaults to True.
        
        Examples:
            Get the number of case management clients enrolled/employed in their first 9 months::

                e.linkages_edu_employ(first_n_months=9)

            Get the number of clients currently enrolled/employed with an age cutoff of 19::

                e.linkages_edu_employ(just_cm=False, ongoing=True, age_cutoff=19)
            
            Get the number of case management clients enrolled/employed excluding workforce development linkages::

                e.linkages_edu_employ(include_wfd=False)
        '''

        workforce = '|Workforce Development' if include_wfd else ''
        query = f'''
        with part as (
        select participant_id, age, birth_date, program_start, service_start,case when datediff({self.q_t2}, service_start) > 45 then 'cont' else 'new' end as newness, 
        case when age < {age_cutoff} then 'juvenile' when age >= {age_cutoff} then 'adult' else 'missing' end as age_group
        from {self.table}
        {f"where service_type = 'Case Management'" if just_cm else ''}),
        cust as(
        select participant_id, custody_status from neon.custody_status
        join (select participant_id, program_start, service_start,max(custody_status_date) as custody_status_date from part
        join neon.custody_status using(participant_id)
        group by participant_id, program_start, service_start) cs using (participant_id, custody_status_date)
        where datediff(custody_status_date, program_start) >-60 and custody_status = 'in custody'),
        intake_info as (
        select participant_id, currently_enrolled, currently_employed from neon.intake
        join (select participant_id, max(intake_date) as intake_date from neon.intake
        group by participant_id) i using(participant_id, intake_date)
        join part using(participant_id)
        where intake_date >= program_start),
        base as (
        select * from part
        left join intake_info using(participant_id)
        left join cust using(participant_id)),
        link_tally as (
        select participant_id, count(case when linkage_type like 'education%' then linkage_id else null end) as edu_links,
        count(case when linkage_type regexp 'employment{workforce}' then linkage_id else null end) as job_links
        from part
        join neon.linkages using(participant_id)
        where program_start <= linked_date and linkage_type regexp "education.*|employment{workforce}" and start_date is not null
        {f"and end_date is null" if ongoing else ''} 
        {f"and DATEDIFF(linked_date, program_start) <= {first_n_months} * 30.5" if first_n_months else ''}
        group by participant_id),
        link_base as (
        select * from base
        left join link_tally using(participant_id))

        select age_group, newness, custody_status, count(distinct participant_id) as total_clients,
        count(distinct case when currently_enrolled = 'yes' then participant_id else null end) as began_enrolled,
        count(distinct case when edu_links > 0 then participant_id else null end) as school_links,
        count(distinct case when (currently_enrolled is null or currently_enrolled = 'no') and edu_links > 0 then participant_id else null end) as newly_enrolled,
        count(distinct case when currently_employed = 'yes' then participant_id else null end) as began_employed,
        count(distinct case when job_links > 0 then participant_id else null end) as job_links,
        count(distinct case when (currently_employed is null or currently_employed = 'no') and job_links > 0 then participant_id else null end) as newly_employed
        from link_base
        group by age_group, newness, custody_status
        order by custody_status asc, newness asc
        '''
        df = self.query_run(query)
        return(df)

    @clipboard_decorator
    def linkages_monthly(self, lclc_initiated = True, just_cm = False):
        '''
        Counts the number of clients linked in the current time frame, and in their first 3/6/9 months

        Parameters:
            lclc_initiated (Bool): Only look at linkages that LCLC initiated. Defaults to True
            just_cm (Bool): Only look at clients receiving case management. Defaults to True

        Examples::
            Get the number of case management clients with lclc-initiated linkages in the current time period and their first 3/6/9 months::
            
                e.linkages_monthly()

            Get the number of all clients with linkages in the time period::

                e.linkages_monthly(just_cm=True)
            
            Get the number of case management clients with linkages in the time periods, including client-initiated linkages::

                e.linkages_monthly(lclc_initiated=False)
        '''


        service_statement = "where service_type = 'case management'" if just_cm else ''
        initiated_statement = "and client_initiated = 'no'" if lclc_initiated else ''
        
        query = f'''with parts as  (select distinct(participant_id), program_start from {self.table}
        {service_statement}),
        base as (select *, timestampdiff(month, program_start, linked_date) month_diff, timestampdiff(month, linked_date, {self.q_t2}) recent_diff from neon.linkages
        join parts using(participant_id)
        where (linked_date > program_start or start_date > program_start) and linked_date <= {self.q_t2} {initiated_statement}),
        recent_links as (
        select participant_id, count(linkage_id) total_links,
        count(case when month_diff < 4 then linkage_id else null end) first_3,
        count(case when month_diff < 7 then linkage_id else null end) first_6,
        count(case when month_diff < 10 then linkage_id else null end) first_9,
        count(case when recent_diff < 1 then linkage_id else null end) this_month
        from base
        group by participant_id)

        select count(distinct participant_id) as total_clients,
        count(case when total_links > 0 then participant_id else null end) as has_links,
        count(case when first_3 > 0 then participant_id else null end) as first_3,
        count(case when first_6 > 0 then participant_id else null end) as first_6,
        count(case when first_9 > 0 then participant_id else null end) as first_9,
        count(case when this_month > 0 then participant_id else null end) as this_month
        from parts
        left join recent_links using(participant_id)'''
        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def linkages_tally(self, lclc_initiated = True, just_cm = False, timeframe = True, distinct_clients = False, group_by = 'linkage_type',link_started = False, link_ongoing = False):
        '''
        Flexible function designed to return linkage information grouped in some way


        Parameters:
            lclc_initiated (Bool): Only look at linkages that LCLC initiated. Defaults to True
            just_cm (Bool): Only look at clients receiving case management. Defaults to True
            timeframe (Bool): Only include records with a linked_date in the timeframe. Defaults to True
            distinct_clients (Bool): Whether only one record should be counted per client. Defaults to False
            group_by (str): The column to group records by (linkage_type, internal_external, linkage_org). Defaults to 'linkage_type'
            link_started (Bool): Only include linkages with a start date. Defaults to False
            link_ongoing (Bool): Only include linkages with no end date. Defaults to False

        Examples:
            Get the types of linkages recorded for all clients in the timeframe::
                
                e.linkages_tally()
            
            Get the number of case management clients with an internal/external linkage at any time::
            
                e.linkages_tally(just_cm=True, timeframe=False, distinct_clients=True, group_by='internal_external')
            
            Get the number of clients with a started linkage of each type in the timeframe::

                e.linkages_tally(distinct_clients=True, link_started=True)
            
            Get the number of clients linked to organizations at any time, with the linkage currently ongoing::

                e.linkages_tally(distinct_clients=True, group_by='linkage_org', link_started=True, link_ongoing=True)
        '''

        service_statement = "where service_type = 'case management'" if just_cm else ''
        initiated_statement = "and client_initiated = 'no'" if lclc_initiated else ''
        
        parameters_list = [f'linked_date between {self.q_t1} and {self.q_t2}' if timeframe else None, 
                    'start_date is not null' if link_started else None, 'end_date is null' if link_ongoing else None]
        better_parameters = 'where ' + ' and '.join(filter(None, parameters_list)) if any(parameters_list) else ''

        query = f'''with parts as  (select distinct(participant_id), program_start from {self.table}
        {service_statement}),
        base as (select *, timestampdiff(month, program_start, linked_date) month_diff, timestampdiff(month, linked_date, {self.q_t2}) recent_diff from neon.linkages
        join parts using(participant_id)
        where (linked_date > program_start or start_date > program_start) and linked_date <= {self.q_t2} {initiated_statement}),
        better_base as(select participant_id, 
        case when linkage_type is null and internal_program is not null then concat('LCLC - ', internal_program) else linkage_type end as linkage_type, 
        internal_external, linkage_org, linked_date, start_date, end_date, comments from base
        {better_parameters})
        select {group_by}, count({'distinct ' if distinct_clients else ''}participant_id) count
        from better_base
        {f'group by {group_by}' if group_by else ''}
        '''
        df = self.query_run(query)
        return(df)


    @clipboard_decorator
    def outreach_elig_tally(self, outreach_only = True, new_clients = False):
        '''
        Counts the number of clients with outreach eligibility forms, and the number who answered yes to each question

        Parameters: 
            outreach_only (Bool): Only include clients currently in outreach. Defaults to True
            new_clients (Bool): Only include new clients. Defaults to False

        Examples:
            Get the number of new outreach clients with eligibility screenings/number of "yes"es for each question::

                e.outreach_elig_tally(new_clients=True)
            
            Get the number of all clients with eligibility screenings//number of "yes"es for each question::

                e.outreach_elig_tally(outreach_only=False)

        '''
        where_statement = f'''where service_type = 'outreach''' if outreach_only else ''
        where_statement = f'''where program_start between {self.q_t1} and {self.q_t2} and program_type regexp "chd.*|community navigation.*|violence.*"''' if new_clients else ''


        if new_clients and outreach_only: 
            where_statement = f'''where service_type = 'outreach' and service_start between {self.q_t1} and {self.q_t2}'''

        new = f'''and service_start between {self.q_t1} and {self.q_t2}''' if new_clients else ''
        query = f'''
        select count(distinct case when ASI = 'yes' then participant_id else null end) ASI,
        count(distinct case when JSI = 'yes' then participant_id else null end) JSI,
        count(distinct case when RVV = 'yes' then participant_id else null end) RVV,
        count(distinct case when ORVV = 'yes' then participant_id else null end) ORVV,
        count(distinct case when VAB = 'yes' then participant_id else null end) VAB,
        count(distinct case when FASI = 'yes' then participant_id else null end) FASI,
        count(distinct case when violent_felony_conviction = 'yes' then participant_id else null end) violent_felony_conviction,
        count(distinct case when known_potential_safety_concerns = 'yes' then participant_id else null end) known_safety_concerns,
        count(distinct case when experienced_trauma = 'yes' then participant_id else null end) experienced_trauma,
        count(distinct case when benfit_from_outreach = 'yes' then participant_id else null end) benfit_from_outreach
        from assess.outreach_eligibility
        join (select participant_id, max(assessment_date) assessment_date from assess.outreach_eligibility
        group by participant_id) o using(participant_id, assessment_date)
        join(select distinct participant_id from {self.table} {where_statement}) s using(participant_id)
        '''
        df = self.query_run(query)
        return df
    

    @clipboard_decorator
    def session_tally (self, session_type = 'Case Management', distinct_participants=True):
        '''
        Tallies the number of sessions, or number of clients in the timeframe

        Parameters:
            session_type: the type of session to count. Defaults to 'Case Management', but could also be 'Outreach'
            distinct_participants (Bool): True counts the number of clients, False counts the number of sessions. Defaults to True
        
        Examples:
            Get the number of clients with a case management session in the timeframe::

                e.session_tally()
            
            Get the number of outreach sessions in the timeframe::

                e.session_tally(session_type='Outreach', distinct_participants=False)
        '''

        session_type = f"'{session_type}'"
        distinct = 'distinct' if distinct_participants else ''
        query = f'''
        with parts as (
        select distinct(participant_id) from {self.table}
        where service_type like {session_type})

        select count(distinct participant_id) as total_parts, 
        count({distinct} case when session_date between {self.q_t1} and {self.q_t2} then participant_id end) as session_attempts,
        count({distinct} case when (session_date between {self.q_t1} and {self.q_t2}) and successful_contact = 'yes' then participant_id end) as successful_sessions
        from parts
        left join (select * from neon.case_sessions where contact_type like {session_type}) c using(participant_id);
        '''
        df = self.query_run(query)
        return(df)
    
    @clipboard_decorator
    def session_frequency(self, session_type = 'Case Management'):
        '''
        Calculates the regularity of client sessions. 

        Parameters:
            session_type: the type of session to count. Defaults to 'Case Management', but could also be 'Outreach'
        
        Examples:
            Get the session regularity of case management clients::
                
                e.session_frequency()
            
            Get the session regularity of outreach clients::

                e.session_frequency(session_type="Outreach")
        '''

        session_type = f"'{session_type}'"
        query = f'''
        with datez as (select *, datediff(service_end, service_start) as case_length from 
        (select participant_id, service_start, case when (service_end is null or service_end > {self.q_t2}) then {self.q_t2} else service_end end as service_end from {self.table}
        where service_type = {session_type}) cm),
        sess_counts as (
        select participant_id, count(participant_id) as session_count from neon.case_sessions
        join datez using(participant_id)
        where successful_contact = 'yes' and contact_type = {session_type} and session_date between service_start and service_end
        group by participant_id),
        freq as (
        select participant_id, case 
            when session_frequency <= 7 then "weekly"
            when session_frequency between 7 and 14 then "every two weeks"
            when session_frequency between 14 and 30.4 then "monthly"
            when session_frequency between 30.4 and 60.8 then "every two months"
            when session_frequency > 60.8  then 'less than every two months'
            when session_frequency is null then 'no sessions recorded'
            end as session_rate
        from (select participant_id, case_length, session_count, case_length/session_count as session_frequency from datez
        left join sess_counts using(participant_id)) d)

        select session_rate, count(participant_id) as cnt
        from freq
        group by session_rate
        order by case when session_rate = 'weekly' then 1
        when session_rate = 'every two weeks' then 2
        when session_rate = 'monthly' then 3
        when session_rate = 'every two months' then 4
        when session_rate = 'less than every two months' then 5
        else 6
        end asc
        '''
        df = self.query_run(query)
        return(df)

class ReferralAsks(Queries):
    def __init__(self, t1, t2, engine, print_SQL = True, clipboard = False, default_table="stints.neon", mycase = True):
        super().__init__(t1, t2, engine, print_SQL, clipboard, default_table, mycase)
    
    def highest_cases(self, attorneys = False):
        '''
        Finds the number of cases for each felony class by team

        Parameters:
            attorneys (Bool): whether to group by attorney or team. Defaults to False

        Examples:
            Get the number cases for each team broken out by highest charge per client::
                
                e.highest_cases()
            
            Get the number cases for each attorney broken out by highest charge per client::

                e.highest_cases()
        '''

        group_by = 'attorneys' if attorneys else 'participant_team'

        query = f'''with base as (
        select * from neon.legal_mycase
        join (select distinct participant_id from {self.table}) n using(participant_id) where (case_start is null or case_start <= {self.q_t2}) and (case_outcome_date is null or case_outcome_date >= {self.q_t1})) 
            , fel_rank as (select *, case when ranking is null then 10 else ranking end better_rank from base b
            left join misc.felony_classes f on b.class_prior_to_trial_plea = f.felony),
            
            highest_felony as (
            select participant_id, legal_id, mycase_id, mycase_name, case_start, 
            case_end, case_status, case_type, violent, juvenile_adult, class_prior_to_trial_plea, class_after_trial_plea, fel_reduction,
            case_outcome, case_outcome_date, sentence, probation_type, probation_requirements, sentence_length,
            expungable_sealable, expunge_seal_elig_date, expunge_seal_date, was_sentence_reduced, reduction_explain, case_entered_date, outcome_entered_date,
            go_to_trial, attorneys, participant_team ,program_start from fel_rank
            join 
            (select participant_id, min(better_rank) as better_rank from 
            fel_rank group by participant_id) fr using(participant_id, better_rank)
            join (select participant_id, attorneys, participant_team from neon.client_teams) ct using(participant_id))

            
        select {group_by}, 
        count(distinct case when class_prior_to_trial_plea = 'Felony X' then mycase_id else null end) as 'Felony X',
        count(distinct case when class_prior_to_trial_plea = 'Felony 1' then mycase_id else null end) as 'Felony 1',
        count(distinct case when class_prior_to_trial_plea regexp 'Felony 2|Felony 3|Felony 4' then mycase_id else null end) as 'Felony 2-4',
        count(distinct case when class_prior_to_trial_plea = 'Misdemeanor A' then mycase_id else null end) as 'Misdemeanor A',
        count(distinct mycase_id) "Total"
        from highest_felony
        group by {group_by}
        
        union all
        
        select "Total",
		count(distinct case when class_prior_to_trial_plea = 'Felony X' then mycase_id else null end) as 'Felony X',
        count(distinct case when class_prior_to_trial_plea = 'Felony 1' then mycase_id else null end) as 'Felony 1',
        count(distinct case when class_prior_to_trial_plea regexp 'Felony 2|Felony 3|Felony 4' then mycase_id else null end) as 'Felony 2-4',
        count(distinct case when class_prior_to_trial_plea = 'Misdemeanor A' then mycase_id else null end) as 'Misdemeanor A',
        count(distinct mycase_id) "Total"
        from highest_felony
        ;'''

        df = self.query_run(query)
        return(df)
    
    def cm_closures(self):
        '''
        Returns the number of closed clients in the timeframe for each case manager

        Example:
            Get the number of case management closures in the timeframe::

                e.cm_closures()
        '''
        
        query = f'''with staff_refs as (select participant_id, full_name, 
        case when a.staff_type like 'outreach%' then 'outreach'
        when a.staff_type like 'case%' then 'case management'
        when a.staff_type like '%attorney%' then 'legal'
        end as 'service_type', staff_start_date, staff_end_date
        from neon.assigned_staff a)

        select full_name as staff_name, count(distinct participant_id) as closed_clients from neon.big_psg
        left join staff_refs using(participant_id, service_type)
        where service_end > {self.q_t1} and service_type = 'Case Management'
        group by full_name'''
        df = self.query_run(query)
        return(df)
    
    def cpic_summary(self):
        '''
        Returns a summary of CPIC notifications in the timeframe

        Example:
            Get a CPIC notification summary::

                e.cm_closures()
        '''

        query = f'''select incident_date, time_notification time_of_notification, did_staff_respond, how_hear, how_notified, num_individuals, num_living, num_deceased, 
        retaliation_future as future_retaliation_potential, comments
        from neon.critical_incidents
        where how_hear like "%cpic%" and notification_date between {self.q_t1} and {self.q_t2}'''
        df = self.query_run(query)
        return(df)
    
    def missing_isp(self):
        '''
        Returns a table of clients missing an ISP

        Example:
            Get a table of ISP-less clients::

                e.missing_isp()
        '''
        query = f'''select participant_id, first_name, last_name, case_manager, cm_start, linkage_count, latest_linkage, isp_start from neon.cm_summary
        where isp_update is null
        order by linkage_count desc'''
        df = self.query_run(query)
        return(df)

    def last_30_days(self, successful_sessions = True):
        '''
        Returns a table of clients without a session in the last 30 days

        Parameters:
            successful_sessions (Bool): Only include sessions where contact was successfully made. Defaults to True
        
        Examples:
            Get a record of clients without a CM session in the last 30 days::

                e.last_30_days()
            
            Get a record of clients without a CM session attempt in the last 30 days::

                e.last_30_days(False)
        '''

        sessions_attempts = 'latest_session' if successful_sessions else 'latest_attempt'
        query = f'''select participant_id, first_name, last_name, case_manager, cm_start, latest_linkage, isp_update latest_isp_update, {sessions_attempts} from neon.cm_summary
        where (latest_linkage is null or datediff({self.q_t1}, latest_linkage) >31)
        and (isp_update is null or datediff({self.q_t1}, isp_update) >31)
        and (latest_session is null or datediff({self.q_t1}, {sessions_attempts}) >31)'''
        df = self.query_run(query)
        return(df)

class IDHS(Queries):
    def __init__(self, t1, t2, engine, print_SQL = True, clipboard = False, default_table="stints.neon",mycase = True):
        super().__init__(t1, t2, engine, print_SQL, clipboard, default_table, mycase)
        self.table_update('idhs', update_default_table = True)
    
    def idhs_enrollment(self):
        '''
        Returns a table of enrollment numbers for IDHS

        Example:
            Get clients enrolled in IDHS and its services::

                e.idhs_enrollment()
        '''

        query = f'''select 'TOTAL' as 'clients', count(distinct case when new_client = 'new' then participant_id else null end) as new,
        count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing,
        count(distinct case when discharged_client = 'program' then participant_id else null end) as discharged
        from {self.table}
        UNION ALL
        select service_type, count(distinct case when new_client = 'new' then participant_id else null end) as new,
        count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing,
        count(distinct case when discharged_client is not null then participant_id else null end) as discharged
        from {self.table}
        group by service_type'''
        df = self.query_run(query)
        return(df)
    
    def idhs_race_gender(self, race_gender = 'race'):
        '''
        Returns a table of client races or genders broken out by new client status

        Parameters:
            race_gender (str): whether to tally 'race' or 'gender'. Defaults to 'race'
        
        Examples:
            See IDHS client races::

                e.idhs_race_gender('race')

            See IDHS client genders::
                
                e.idhs_race_gender('gender')
        '''

        query = f'''
        select {race_gender}, count(distinct case when new_client = 'new' then participant_id else null end) as new,
        count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
        from {self.table}
        group by {race_gender}
        '''
        df = self.query_run(query)
        return(df)

    def idhs_language(self):
        '''
        Counts participant primary languages

        Example:

            Get IDHS client primary languages::

                e.idhs_language()
        '''
        query = f'''select new_client, language_primary, count(distinct participant_id)
        from {self.table}
        group by new_client, language_primary'''
        df = self.query_run(query)
        return df

    def idhs_age(self, ppr = False):
        '''
        Returns a table of client ages broken out by new client status

        Parameters:
            ppr (Bool): whether to use the age groups on the PPR form. Defaults to False
        
        Examples:
            Get IDHS client ages for the PPR::

                e.idhs_age(True)
            
            Get IDHS client ages for the CVI::

                e.idhs_age(False)
        '''
        if ppr:
            query = f'''
            select 'Under 18' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) <18
            UNION ALL
            select '18-24' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) BETWEEN 18 AND 24
            UNION ALL
            select '25+' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) > 24
            UNION ALL 
            select 'MISSING' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where birth_date is null'''
        else:
            query = f'''
            select '11-13' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) BETWEEN 11 AND 13
            UNION ALL
            select '14-17' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) BETWEEN 14 AND 17
            UNION ALL
            select '18-24' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) BETWEEN 18 AND 24
            UNION ALL
            select '25+' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where TIMESTAMPDIFF(YEAR, birth_date, grant_start) > 24
            UNION ALL 
            select 'MISSING' as age_range, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from {self.table}
            where birth_date is null
            '''
        df = self.query_run(query)
        return(df)
    
    
    def idhs_linkages(self, internal_external = False):
        '''
        Returns a table of linkage information for the quarter
        
        Parameters:
            internal_external: whether to group by internal/external functions. Defaults to False
        
        Examples:
            Get IDHS client linkages by linkage category::

                e.idhs_linkages()
            
            Get a breakdown of internal/external linkages for IDHS clients::

                e.idhs_linkages(True)
        '''
        
        
        int_ext = 'internal_external' if internal_external else 'linkage_type'
        query = f'''
        with link as(
        select participant_id, new_client, case when linkage_type is null then internal_program else linkage_type end as linkage_type, internal_external, linkage_org from neon.linkages
        join (select distinct participant_id, new_client from {self.table}) i using(participant_id)
        where client_initiated = 'no' and linked_date between {self.q_t1} and {self.q_t2})

        select {int_ext}, count(case when new_client = 'new' then participant_id else null end) as new_links,
        count(case when new_client = 'continuing' then participant_id else null end) as cont_links
        from link
        group by {int_ext}
        '''
        df = self.query_run(query)
        return(df)

    def idhs_linkages_detailed(self):
        '''
        Returns a Frankensteined table of other forms of 'detail-level services'. Currently includes in-kind services, outreach/cm assessments, and topics of cm sessions.
        
        Example:
            Get a table of non-linkages services IDHS clients were connected to::

                e.idhs_linkages_detailed()
        '''
        def in_kind_services():
            query = f'''
            select concat('Received ', service_type) detail_service_type, 
            count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing
            from stints.neon
            join (select distinct participant_id, new_client from participants.idhs) i using(participant_id)
            where grant_type not like "IDHS VP"
            group by service_type'''
            df = self.query_run(query)
            return(df)

        def assessments_plus():
            query = f'''
            with part as (select distinct participant_id, new_client from participants.idhs),

            isp_updates as(select 'Received an ISP update' detail_service_type, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing from (select * from isp_tracker
            join part using(participant_id)
            where latest_update between {self.q_t1} and {self.q_t2}) isp),

            cm_assess as(
            select 'Got a cm assessment' cnt, count(distinct case when new_client = 'new' then participant_id else null end) as new_assess,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as cont_assess
            from(
            select participant_id, new_client, count(score) as num_cm_assess from assess.cm_long
            join part using(participant_id)
            where assessment_date between {self.q_t1} and {self.q_t2}
            group by participant_id, new_client) i),

            ow_assess as (select 'Got an ow assessment' cnt, count(distinct case when new_client = 'new' then participant_id else null end) as new_assess,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as cont_assess from (select * from assess.outreach_tracker
            right join part using(participant_id)
            where (latest_elig between {self.q_t1} and {self.q_t2}) or (latest_assessment between {self.q_t1} and {self.q_t2}) or (latest_intervention between {self.q_t1} and {self.q_t2})) o),

            successful_sessions as (select concat("Successful ", contact_type, " Session") sessions, 
            count(distinct case when new_client = 'new' then participant_id else null end) as new_in_kind,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as cont_in_kind
            from (
            select p.participant_id, new_client, contact_type, session_date, description from neon.case_sessions c
            join (select participant_id, new_client, service_type from participants.idhs) p on p.participant_id = c.participant_id and p.service_type = c.contact_type
            where (session_date between {self.q_t1} and {self.q_t2}) and successful_contact = 'Yes') i
            group by contact_type)

            select * from isp_updates
            union all
            select * from cm_assess
            union all
            select * from ow_assess
            union all
            select * from successful_sessions
            '''
            df = self.query_run(query)
            return(df)
        
        def cm_sessions():
            query = f'''

            with sess as(select participant_id, focus_contact, contact_type, new_client, description from neon.case_sessions
            join (select distinct participant_id, new_client from participants.idhs where service_type = 'case management') i using(participant_id)
            where (session_date between {self.q_t1} and {self.q_t2}) and successful_contact = 'Yes' and focus_contact is not null),
            separated as
            (select participant_id, new_client, contact_type, SUBSTRING_INDEX(SUBSTRING_INDEX(focus_contact, ', ', n), ', ', -1) AS separated_focus
            from sess
            JOIN (
                SELECT 1 AS n UNION ALL
                SELECT 2 UNION ALL
                SELECT 3 UNION ALL
                SELECT 4 UNION ALL
                SELECT 5 UNION ALL
                SELECT 6 UNION ALL
                SELECT 7 UNION ALL
                SELECT 8 UNION ALL
                SELECT 9
            ) AS numbers
            ON CHAR_LENGTH(focus_contact) - CHAR_LENGTH(REPLACE(focus_contact, ',', '')) >= n - 1)

            select separated_focus detail_service_type, count(distinct case when new_client = 'new' then participant_id else null end) as new,
            count(distinct case when new_client = 'continuing' then participant_id else null end) as continuing from 
            separated
            group by separated_focus
            '''
            df = self.query_run(query)
            return(df)
        
        sessions = cm_sessions().set_index('detail_service_type')
        assess = assessments_plus().set_index('detail_service_type')
        in_kind = in_kind_services().set_index('detail_service_type')
        df = pd.concat([in_kind, assess, sessions], keys=['In-Kind Services','Other Detail-Level Services','Focus of CM Sessions'])
        df = df.reset_index()
        df = df.rename(columns={'level_0':'data_source'})
        return df


    def idhs_incidents(self, CPIC = True):
        '''
        Returns incident analysis for CPIC/non-CPIC notifications

        Example:
            Get a CPIC notification breakdown for IDHS::

                e.idhs_incidents()
            
            Get a non-CPIC notification breakdown for IDHS::

                e.idhs_incidents(False)
        '''
        if CPIC:
            query = f'''SELECT type_incident,
            count(case when num_deceased > 0 then incident_id else null end) as fatal,
            count(case when num_deceased = 0 then incident_id else null end) as non_fatal
            FROM neon.critical_incidents
            where how_hear regexp '.*cpic.*' and incident_date between {self.q_t1} and {self.q_t2}
            group by type_incident'''
        else:
            query = f'''select how_hear, count(incident_id) from neon.critical_incidents
            where incident_date between {self.q_t1} and {self.q_t2} and how_hear not regexp '.*cpic.*'
            group by how_hear'''
        df = self.query_run(query)
        return df
    


    

