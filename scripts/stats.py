#!/usr/bin/env python3

import subprocess
import smtplib
import sys
import shutil
import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import urllib.request
from datetime import datetime, timedelta, date
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from urllib.parse import urlparse

# Environment configuration
server_name = "g2nb Workspace"        # Name of the repo server to report
include_extension = False             # Include the right column that polls GP server?
user_dir = '/data/lab/users/'         # The dir where user data is stored
stats_dir = '/data/lab/counters/'     # Where to save the stats state
data_dir = '/data/lab/'               # Directory with JupyterHub database
sudo_req = 'sudo '                    # Make blank if sudo is not required
test_email = 'user@domain.org'        # Email to send to when run with --test
admin_login = 'username:password'     # Admin login credentials for GP server
s3_bucket = 'gpnotebook-backup'       # s3 bucket to check for GP Broad stats
DB_PATH = '//data/lab/usage.sqlite'   # Path to usage events database
MAIL_SERVER = 'smtp-server-url'       # URL pointing at the SMTP server
MAIL_USERNAME = 'username'            # Username for SMTP server, leave None if N/A
MAIL_PASSWORD = 'password'            # Password for SMTP server


# Handle arguments
test_run = True if (len(sys.argv) >= 2 and sys.argv[1] == '--test') else False


def _poll_docker(image):
    """
    Poll DockerHub for stats on the GenePattern images
    :param image:
    :return:
    """
    request = urllib.request.Request('https://registry.hub.docker.com/v2/repositories/genepattern/' + image + '/')
    response = urllib.request.urlopen(request)
    json_str = response.read().decode('utf-8')
    image_json = json.loads(json_str)
    return {'stars': image_json['star_count'], 'pulls': image_json['pull_count']}


def get_docker():
    """
    Gather all the available Docker stats
    :return:
    """
    docker = {'notebook': _poll_docker('genepattern-notebook'),
              'jupyterhub': {'stars': 1, 'pulls': 180}}
    return docker


def _poll_genepattern(gp_url, tag):
    """
    Poll the provided GenePattern server for the number of GenePattern Notebook jobs launched in the last week

    :param gp_url: The URL of the GenePattern server, not including /gp...
    :return: Return the number of GenePattern Notebook jobs launched on this server
    """
    try:
        request = urllib.request.Request(
            gp_url + '/gp/rest/v1/jobs/?tag=' + tag + '&pageSize=1000&includeChildren=true&includeOutputFiles=false&includePermissions=false')
        base64string = base64.encodebytes(bytearray(admin_login, 'utf-8')).decode('utf-8').replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        response = urllib.request.urlopen(request)
        json_str = response.read().decode('utf-8')
        jobs_json = json.loads(json_str)
        count = 0
    except urllib.request.URLError:
        print('ERROR getting stats from ' + gp_url)
        return 0

    for job in jobs_json['items']:
        timestamp = job['dateSubmitted']
        date = datetime.strptime(timestamp.split('T')[0], '%Y-%m-%d')
        if date >= datetime.now() - timedelta(days=7):
            count += 1
        if 'children' in job:
            child_count = len(job['children']['items'])
            count += child_count

    return count


def get_total_jobs(weekly_jobs):
    """
    Add latest weekly jobs to the total jobs count
    :param weekly_jobs:
    :return:
    """

    # Read the file of total jobs
    jobs_file = open(stats_dir + 'jobs.lst', 'r')
    jobs_list = jobs_file.readlines()
    jobs_list = [j.strip() for j in jobs_list]  # Clean new lines

    # Create the total jobs object
    total_jobs = {}
    total_jobs['prod'] = int(jobs_list[0]) + (0 if not isinstance(weekly_jobs['prod'], int) else weekly_jobs['prod'])
    total_jobs['broad'] = int(jobs_list[1]) + (0 if not isinstance(weekly_jobs['broad'], int) else weekly_jobs['broad'])
    total_jobs['iu'] = int(jobs_list[2]) + (0 if not isinstance(weekly_jobs['iu'], int) else weekly_jobs['iu'])
    total_jobs['aws'] = int(jobs_list[3]) + (0 if not isinstance(weekly_jobs['aws'], int) else weekly_jobs['aws'])
    total_jobs['prod-py'] = int(jobs_list[4]) + (0 if not isinstance(weekly_jobs['prod-py'], int) else weekly_jobs['prod-py'])
    total_jobs['broad-py'] = int(jobs_list[5]) + (0 if not isinstance(weekly_jobs['broad-py'], int) else weekly_jobs['broad-py'])
    total_jobs['iu-py'] = int(jobs_list[6]) + (0 if not isinstance(weekly_jobs['iu-py'], int) else weekly_jobs['iu-py'])
    total_jobs['aws-py'] = int(jobs_list[7]) + (0 if not isinstance(weekly_jobs['aws-py'], int) else weekly_jobs['aws-py'])

    # Write the new totals back to the file
    if not test_run:
        jobs_file = open(stats_dir + 'jobs.lst', 'w')
        jobs_file.write("%s\n" % total_jobs['prod'])
        jobs_file.write("%s\n" % total_jobs['broad'])
        jobs_file.write("%s\n" % total_jobs['iu'])
        jobs_file.write("%s\n" % total_jobs['aws'])
        jobs_file.write("%s\n" % total_jobs['prod-py'])
        jobs_file.write("%s\n" % total_jobs['broad-py'])
        jobs_file.write("%s\n" % total_jobs['iu-py'])
        jobs_file.write("%s\n" % total_jobs['aws-py'])
        jobs_file.close()

    return total_jobs


def _read_s3_stats(log_file):
    """
    Read the s3 file with the logged job counts
    """

    # Copy the s3 log file to local disk
    subprocess.getstatusoutput('aws s3 cp s3://' + s3_bucket + '/' + log_file + ' ' + stats_dir + log_file)

    # Read the log file
    jobs_file = open(stats_dir + log_file, 'r')
    jobs_list = jobs_file.readlines()
    jobs_list = [j.strip() for j in jobs_list]  # Clean new lines
    jobs_file.close()

    return [int(jobs_list[0]), int(jobs_list[1])]


def get_weekly_jobs():
    """
    Assemble the number of GenePattern Notebook jobs launched on each server
    """
    weekly_jobs = {'prod': 0,  # This server has been decommissioned
                   'prod-py': 0,

                   'iu': _poll_genepattern('https://gp.indiana.edu', 'GenePattern%20Notebook'),
                   'iu-py': _poll_genepattern('https://gp.indiana.edu', 'GenePattern%20Python%20Client'),

                   'aws': _poll_genepattern('https://cloud.genepattern.org', 'GenePattern%20Notebook'),
                   'aws-py': _poll_genepattern('https://cloud.genepattern.org', 'GenePattern%20Python%20Client'),

                   'broad': _read_s3_stats('job_count.log')[0],
                   'broad-py': _read_s3_stats('job_count.log')[1]}

    return weekly_jobs


def get_user_disk():
    """
    Handle determining disk usage on this VM
    """
    users = []

    if not test_run:
        # Get the amount of disk usage per user

        cmd_out = subprocess.getstatusoutput(sudo_req + 'du -h --max-depth=1 ' + user_dir + ' | sort -hr')[1]
        cmd_lines = cmd_out.split('\n')

        # Iterate over each user's line
        for line in cmd_lines:
            cmd_parts = line.split('\t')

            # Clean the username
            cleaned_name = cmd_parts[1][len(data_dir):]

            # Ignore the base directory
            if cleaned_name == '':
                continue

            # Add the user stats to the list
            users.append([cmd_parts[0], cleaned_name])

    # Create the HTML row list for top 10 users
    user_rows = ''
    for i in range(len(users[:10])):
        user_rows += '<tr><td>' + users[i][1] + '</td><td>' + users[i][0] + '</td></tr>'

    return user_rows


def get_disk_usage():
    """
    Handle determining disk usage on this VM
    """
    disk = {}

    # Get the amount of general disk space used
    cmd_out = subprocess.getstatusoutput('df -h | grep "/dev/xvda1"')[1]
    cmd_parts = cmd_out.split()
    disk["gen_disk_used"] = cmd_parts[2]
    disk["gen_disk_total"] = cmd_parts[3]
    disk["gen_disk_percent"] = cmd_parts[4]

    # Get the amount of Docker disk space used
    cmd_out = subprocess.getstatusoutput('df -h | grep "tmpfs"')[1]
    cmd_parts = cmd_out.split()
    disk["docker_disk_used"] = cmd_parts[2]
    disk["docker_disk_total"] = cmd_parts[3]
    disk["docker_disk_percent"] = cmd_parts[4]

    return disk


def get_nb_count():
    """
    Count the number of notebooks on the server
    """

    # Gather a list of all running containers
    # cmd_out = subprocess.getstatusoutput(sudo_req + 'docker ps')[1]

    # For each container, get the count
    nb_count = {'week': 0,
                'total': 0,
                'files_week': 0,
                'files_total': 0}

    if not test_run:
        # Weekly query
        cmd_out = subprocess.getstatusoutput("find " + data_dir + " -type f -not -path '*/\.*' -mtime -7 -name *.ipynb | wc -l")[1]
        user_week = int(cmd_out.strip())
        nb_count['week'] += user_week

        # Total query
        cmd_out = subprocess.getstatusoutput("find " + data_dir + " -type f -not -path '*/\.*' -name *.ipynb | wc -l")[1]
        user_total = int(cmd_out.strip())
        nb_count['total'] += user_total

        # All files query, weekly
        cmd_out = subprocess.getstatusoutput("find " + data_dir + " -type f -not -path '*/\.*' -mtime -7 | wc -l")[1]
        files_week = int(cmd_out.strip())
        nb_count['files_week'] += files_week - user_week

        # All files query, total
        cmd_out = subprocess.getstatusoutput("find " + data_dir + " -type f -not -path '*/\.*' | wc -l")[1]
        files_total = int(cmd_out.strip())
        nb_count['files_total'] += files_total - user_total

    return nb_count


def _genepattern_users():
    """
    Poll the provided GenePattern server for the number of GenePattern Notebook jobs launched in the last week

    :return: Return the number of GenePattern Notebook jobs launched on this server
    """
    try:
        start_date = datetime.strftime(datetime.now() - timedelta(days=7), "%Y-%m-%d+01:01:01")
        request = urllib.request.Request('https:/cloud.genepattern.org/gp/rest/v1/users/new?start=' + start_date)
        base64string = base64.encodebytes(bytearray(admin_login, 'utf-8')).decode('utf-8').replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        response = urllib.request.urlopen(request)
        json_str = response.read().decode('utf-8')
        user_json = json.loads(json_str)
        return user_json['users']
    except urllib.request.URLError:
        return 'ERROR'


def _genepattern_users_stopgap():
    """
    Temporary workaround for retrieving new users from the GP server
    :return:
    """

    try:
        start_date = datetime.strftime(datetime.now() - timedelta(days=7), "%Y-%m-%d")
        end_date = datetime.strftime(datetime.now(), "%Y-%m-%d")

        # http://cloud.genepattern.org/gp/rest/v1/usagestats/user_summary/2018-08-14/2018-08-21
        request = urllib.request.Request('https://cloud.genepattern.org/gp/rest/v1/usagestats/user_summary/' + start_date + '/' + end_date)
        base64string = base64.encodebytes(bytearray(admin_login, 'utf-8')).decode('utf-8').replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        response = urllib.request.urlopen(request)
        json_str = response.read().decode('utf-8')
        user_json = json.loads(json_str)

        return user_json['NewUsers']
    except urllib.request.URLError:
        return 'ERROR'


def _get_user_email(gp_users, user):
    """
    Get user email from new user data (both old and temp style JSON structures)
    :param gp_users:
    :param user:
    :return:
    """

    # If list is an error, return error
    if gp_users == 'ERROR':
        return 'ERROR'

    # Iterate over the list of users, return matching user's email
    email = None
    for u in gp_users:
        if 'username' in u:
            if u['username'].lower() == user:
                email = u['email']
                break
        elif 'user_id' in u:
            if u['user_id'].lower() == user:
                email = u['email']
                break

    # If no user was found, return blank
    if email:
        return email
    else:
        return ''


def get_returning_users(returning_count):
    """
    Returns a list of returning users
    :return:
    """
    # Read the exclusion file
    if os.path.exists(stats_dir + 'exclusion.lst'):
        exclusion_file = open(stats_dir + 'exclusion.lst', 'r')
        exclusion_list = exclusion_file.readlines()
        exclusion_list = [u.strip() for u in exclusion_list]
    else:
        exclusion_list = []

    # Read the user database
    cmd_out = subprocess.getstatusoutput("sqlite3 " + data_dir + "jupyterhub.sqlite \"select name from users order by last_activity\"")[1]
    all_users = cmd_out.split('\n')

    # Exclude members of the lab
    users_minus_exclusions = [user for user in all_users if user not in exclusion_list and not user.startswith('guest')]
    return users_minus_exclusions[:returning_count], returning_count


def get_users():
    """
    Counts the number of new and returning users to the GP Notebook Repo
    :return:
    """
    users = {}

    # Read the file of existing users
    user_file = open(stats_dir + 'users.lst', 'r')
    user_list = user_file.readlines()
    user_list = [u.strip() for u in user_list]  # Clean new lines

    # Gather a list of all running containers
    cmd_out = subprocess.getstatusoutput(
            "sqlite3 " + data_dir + "jupyterhub.sqlite \"select name from users where last_activity > (SELECT DATETIME('now', '-7 day'));\"")[1]
    containers = cmd_out.split('\n')

    # Get a list of all new users
    new_users = list(set(containers) - set(user_list))

    # Get a list of all returning users
    returning_count = len(set(user_list) & set(containers))
    returning_users, returning_count = get_returning_users(returning_count)

    # Query the GenePattern public server for info about new users
    gp_users = _genepattern_users_stopgap()

    # Create the HTML row list for all new users
    new_users_rows = ''
    for user in new_users:
        # Get the user email or fall back to blank
        email = _get_user_email(gp_users, user)
        new_users_rows = new_users_rows + '<tr><td>' + user + '</td><td>' + email + '</td></tr>'

    # Create the HTML row list for all returning users
    returning_users_rows = ''
    for user in returning_users:
        returning_users_rows = returning_users_rows + '<tr><td>' + user + '</td></tr>'

    # Get the sets of users
    users['returning'] = returning_count
    users['new'] = len(set(containers) - set(user_list))
    users['total'] = len(set(user_list) | set(containers))
    users['new_users'] = new_users_rows
    users['returning_users'] = returning_users_rows

    # Update the users file
    if not test_run:
        user_file = open(stats_dir + 'users.lst', 'w')
        for u in (set(user_list) | set(containers)):
            user_file.write("%s\n" % u)
        user_file.close()

    return users


def get_logins():
    """
    Get number of logins this week
    :return:
    """
    logins = {}

    # Count the number of logins in the weekly log
    cmd_out = subprocess.getstatusoutput('cat ' + data_dir + 'jupyterhub.log | grep -c "User logged in"')[1]
    logins['week'] = int(cmd_out.strip())

    # Read the total number of logins
    login_file = open(stats_dir + 'logins.log', 'r')
    total_count = login_file.read().strip()
    if len(total_count) == 0:  # Handle an empty file
        total_count = 0
    else:
        total_count = int(total_count)

    # Add logins and update file
    total_count += logins['week']
    logins['total'] = total_count
    if not test_run:
        login_file = open(stats_dir + 'logins.log', 'w')
        login_file.write(str(total_count))
        login_file.close()

    # Move the log to backup
    if not test_run:
        shutil.copyfileobj(open(data_dir + 'jupyterhub.log', 'r'), open(stats_dir + 'jupyterhub.log', 'w'))
        subprocess.getstatusoutput('> ' + data_dir + 'jupyterhub.log')

    return logins


def get_nb_usage():
    """
    Query repo for notebook usage
    :return:
    """
    cmd_out = subprocess.getstatusoutput(f"sqlite3 {data_dir}/projects.sqlite 'select name, copied from projects'")[1]
    lines = cmd_out.split('\n')
    nb_tuples = {}
    for l in lines:
        name, usage = l.split('|')
        nb_tuples[name] = int(usage)

    # Sort notebooks by copied
    sorted_nb_tuples = sorted(nb_tuples.items(), key=lambda kv: kv[1], reverse=True)

    # Create the HTML row list for top 10 notebooks
    nb_rows = ''
    for i in range(len(sorted_nb_tuples[:10])):
        nb_rows += f'<tr><td>{sorted_nb_tuples[i][0]}</td><td>{sorted_nb_tuples[i][1]}</td></tr>'

    return nb_rows


def get_nb_updates():
    cmd_out = subprocess.getstatusoutput(f"sqlite3 {data_dir}/projects.sqlite \"select p.name, u.updated, u.comment from projects p, updates u where p.id = u.project_id and u.updated > (SELECT DATETIME('now', '-7 day'))\"")[1]
    lines = cmd_out.split('\n')

    nb_updates = ''
    for l in lines:
        if l.strip(): name, updated, comment = l.split('|')
        else: name, comment = ['None', 'None']
        nb_updates += f"<tr><td>{name}</td><td>{comment}</td></tr>"
    return nb_updates


def get_event_stats(start_date=None, end_date=None):
    Base = declarative_base()

    class Database:
        _db_singleton = None
        db = None
        Session = None

        def __init__(self):
            self.db = create_engine(f'sqlite://{DB_PATH}', echo=False)
            self.Session = sessionmaker(bind=self.db)
            Base.metadata.create_all(self.db)

        @classmethod
        def instance(cls):
            if cls._db_singleton is None:
                cls._db_singleton = Database()
            return cls._db_singleton

    class UsageEvent(Base):
        """ORM model representing a usage event"""
        __tablename__ = 'events'

        id = Column(Integer, primary_key=True)
        event_token = Column(String(127))
        description = Column(String(255))
        created = Column(DateTime, default=datetime.utcnow)

        def __init__(self, **kwargs):
            super(UsageEvent, self).__init__()
            self.__dict__.update(kwargs)

        def save(self):
            session = Database.instance().Session()
            session.add(self)
            session.commit()
            session.close()

        def json(self):
            data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
            for k in data:
                if isinstance(data[k], datetime): data[k] = str(data[k])  # Special case for datetimes
            return data

        @staticmethod
        def get(event_token=None, start_date=None, end_date=None):
            # Query the database
            session = Database.instance().Session()
            query = session.query(UsageEvent)
            if event_token is not None: query = query.filter(UsageEvent.event_token == event_token)
            if start_date is not None: query = query.filter(UsageEvent.created > start_date)
            if end_date is not None: query = query.filter(UsageEvent.created < end_date)
            results = query.all()
            session.close()
            return results


    # Get all usage events in the specified date range
    events = UsageEvent.get(start_date=start_date, end_date=end_date)

    # Create a new dict to store all the compiled stats
    event_stats = {}

    # Loop over each usage event
    for e in events:

        # Special case for unknown tokens
        if e.event_token == '': e.event_token = 'unknown'

        # Lazily initialize event_stats and increment counts for each event_token
        if e.event_token in event_stats: event_stats[e.event_token]['count'] += 1
        else: event_stats[e.event_token] = {'count': 1}

        # Note the latest time the event happened
        if 'latest' not in event_stats[e.event_token]:
            event_stats[e.event_token]['latest'] = e.created
        elif event_stats[e.event_token]['latest'] < e.created:
            event_stats[e.event_token]['latest'] = e.created

        # Note the earliest time the event happened
        if 'earliest' not in event_stats[e.event_token]:
            event_stats[e.event_token]['earliest'] = e.created
        elif event_stats[e.event_token]['earliest'] > e.created:
            event_stats[e.event_token]['earliest'] = e.created

        # Special parsing for tool_run
        if e.event_token == 'tool_run':
            # Lazily initialize the list of tools
            if 'tools' not in event_stats[e.event_token]:
                event_stats[e.event_token]['tools'] = {}

            # Parse the description and handle blanks
            origin, id, tool = e.description.split('|')
            if origin == '': origin = 'unknown'
            if tool == '': tool = 'unknown'

            # Lazily initialize the specific tool
            if tool not in event_stats[e.event_token]['tools']:
                event_stats[e.event_token]['tools'][tool] = {'count': 1}
            else:
                event_stats[e.event_token]['tools'][tool]['count'] += 1

        # Special parsing for project_launch
        elif e.event_token == 'project_launch':
            # Lazily initialize the list of users
            if 'users' not in event_stats[e.event_token]:
                event_stats[e.event_token]['users'] = {}

            # Parse the description
            user, project = e.description.split('|')

            # Lazily initialize the specific user
            if user not in event_stats[e.event_token]['users']:
                event_stats[e.event_token]['users'][user] = {'count': 1}
            else:
                event_stats[e.event_token]['users'][user]['count'] += 1

        # Special parsing for labextension_load
        elif e.event_token == 'labextension_load':
            # Lazily initialize the list of domains
            if 'domains' not in event_stats[e.event_token]:
                event_stats[e.event_token]['domains'] = {}

            # Parse the description
            url = urlparse(e.description)
            hostname = url.hostname

            # Lazily initialize the specific domain or increment the count
            if hostname not in event_stats[e.event_token]['domains']:
                event_stats[e.event_token]['domains'][hostname] = {'count': 1}
            else:
                event_stats[e.event_token]['domains'][hostname]['count'] += 1

        # Handle other event_tokens
        # else:
        #     # Lazily initialize the list of descriptions
        #     if e.event_token not in event_stats:
        #         event_stats[e.event_token] = {}
        #     if 'descriptions' not in event_stats[e.event_token]:
        #         event_stats[e.event_token]['descriptions'] = []
        #
        #     # Append to the list
        #     event_stats[e.event_token]['descriptions'].append[e.description]

    # Ensure that the expected event types have at least been initialized
    if 'tool_run' not in event_stats: event_stats['tool_run'] = { 'count': 0, 'tools': [] }
    if 'project_launch' not in event_stats: event_stats['project_launch'] = { 'count': 0, 'users': [] }
    if 'labextension_load' not in event_stats: event_stats['labextension_load'] = { 'count': 0, 'domains': [] }

    return event_stats


def users_table(users):
    return f"""
        <h3>Repository users</h3>
        <table border="1">
            <tr>
                <th>Users</th>
                <th>#</th>
            </tr>
            <tr>
                <td>All-time users</td>
                <td>{users['total']}</td>
            </tr>
            <tr>
                <td>Weekly returning</td>
                <td>{users['returning']}</td>
            </tr>
            <tr>
                <td>Weekly new</td>
                <td>{users['new']}</td>
            </tr>
        </table>
    """


def logins_table(logins):
    return f"""
        <h3>Repository user logins</h3>
        <table border="1">
            <tr>
                <th>Logins</th>
                <th>#</th>
            </tr>
            <tr>
                <td>All-time total</td>
                <td>{logins['total']}</td>
            </tr>
            <tr>
                <td>This week</td>
                <td>{logins['week']}</td>
            </tr>
        </table>
    """


def notebooks_table(nb_count):
    return f"""
        <h3>Repository notebooks created</h3>
        <table border="1">
            <tr>
                <th>Notebooks</th>
                <th>#</th>
            </tr>
            <tr>
                <td>Total in repository</td>
                <td>{nb_count['total']}</td>
            </tr>
            <tr>
                <td>Modified this week</td>
                <td>{nb_count['week']}</td>
            </tr>
        </table>
    """


def disk_table(disk):
    return f"""
        <h3>Repository disk space used</h3>
        <table border="1">
            <tr>
                <th>File System</th>
                <th>Used</th>
                <th>Total</th>
                <th>Percent</th>
            </tr>
            <tr>
                <td>General Disk</td>
                <td>{disk["gen_disk_used"]}</td>
                <td>{disk["gen_disk_total"]}</td>
                <td>{disk["gen_disk_percent"]}</td>
            </tr>
            <tr>
                <td>Docker Disk</td>
                <td>{disk["docker_disk_used"]}</td>
                <td>{disk["docker_disk_total"]}</td>
                <td>{disk["docker_disk_percent"]}</td>
            </tr>
        </table>
    """


def files_table(nb_count):
    return f"""
        <h3>Repository non-notebook files</h3>
        <table border="1">
            <tr>
                <th>Files</th>
                <th>#</th>
            </tr>
            <tr>
                <td>Total in repository</td>
                <td>{nb_count['files_total']}</td>
            </tr>
            <tr>
                <td>Modified this week</td>
                <td>{nb_count['files_week']}</td>
            </tr>
        </table>
    """


def new_users_table(users):
    return f"""
        <h3>New Users This Week</h3>
        <table border="1">
            <tr>
                <th>Username</th>
                <th>Email</th>
            </tr>
            {users['new_users']}
        </table>
    """


def returning_users_table(users):
    return f"""
        <h3>Returning Users This Week</h3>
        <table border="1">
            <tr>
                <th>Username</th>
            </tr>
            {users['returning_users']}
        </table>
    """


def updated_notebooks_table(nb_updates):
    return f"""
        <h3>Public Notebooks Created or Updated This Week</h3>
        <table border="1">
        <tr><th>Name</th><th>Comment</th></tr>
        {nb_updates}
        </table>
    """


def top_notebooks_table(nb_usage):
    return f"""
        <h3>Top 10 Public Notebooks Since 2019-02-22</h3>
        <table border="1">
            <tr>
                <th>Notebook</th>
                <th>Copies</th>
            </tr>
            {nb_usage}
        </table>
    """


def top_disk_table(user_disk):
    return f"""
        <h3>User Disk Usage Top 10</h3>
        <table border="1">
            <tr>
                <th>Username</th>
                <th>Disk Usage</th>
            </tr>
            {user_disk}
        </table>
    """


def environment_starts_table(event_stats):
    env_counts = sorted(event_stats['labextension_load']['domains'].items(), key=lambda x: x[1]['count'], reverse=True)
    env_rows = ''
    for u in env_counts:
        env_rows += f"<tr><td>{u[0]}</td><td>{u[1]['count']}</td></tr>"
    return f"""
        <h3>Weekly Environment Starts</h3>
        <table border="1">
            <tr>
                <th>Domain</th>
                <th>Count</th>
            </tr>
            {env_rows}
        </table>
    """


def top_tools_table(event_stats):
    tool_counts = sorted(event_stats['tool_run']['tools'].items(), key=lambda x: x[1]['count'], reverse=True)
    tool_counts = tool_counts[:10]
    tool_rows = ''
    for u in tool_counts:
        tool_rows += f"<tr><td>{u[0]}</td><td>{u[1]['count']}</td></tr>"
    return f"""
        <h3>Top Weekly Tools</h3>
        <table border="1">
            <tr>
                <th>Tool</th>
                <th>Tool Runs</th>
            </tr>
            {tool_rows}
        </table>
    """


def top_users_table(event_stats):
    user_counts = sorted(event_stats['project_launch']['users'].items(), key=lambda x: x[1]['count'], reverse=True)
    user_counts = user_counts[:10]
    user_rows = ''
    for u in user_counts:
        user_rows += f"<tr><td>{u[0]}</td><td>{u[1]['count']}</td></tr>"
    return f"""
        <h3>Top Weekly Workspace Users</h3>
        <table border="1">
            <tr>
                <th>User</th>
                <th>Projects Launched</th>
            </tr>
            {user_rows}
        </table>
    """


def send_mail(users, logins, disk, nb_count, weekly_jobs, docker, total_jobs, nb_updates, nb_usage, user_disk, event_stats):
    """
    Send the weekly report in an email
    :return:
    """
    today = str(date.today())
    fromaddr = "gp-info@broadinstitute.org" if not test_run else test_email
    toaddr = "gp-dev@broadinstitute.org" if not test_run else test_email
    msg = MIMEMultipart()
    msg['From'] = fromaddr
    msg['To'] = toaddr
    msg['Subject'] = f"{server_name} Usage Statistics, week ending {today}"

    body = f"""
        <html>
            <body>
                <h1>{server_name} Report, week ending {today}</h1>
                <table width="100%%">
                    <tr>
                        <td width="50%%" valign="top">
                            <h2>Notebook Repository</h2>
                            {users_table(users)}

                            {logins_table(logins)}

                            {notebooks_table(nb_count)}

                            {files_table(nb_count)}

                            {disk_table(disk)}

                            {new_users_table(users)}
                            
                            {returning_users_table(users)}
                            
                            {top_users_table(event_stats)}
                        </td>
                        <td width="50%%" valign="top">
                        
                            {environment_starts_table(event_stats)}
        """

    if include_extension:
        body = body + f"""
                            <h2>Notebook Extension</h2>
                            <h3>Notebook jobs run this week</h3>
                            <table border="1">
                                <tr>
                                    <th>Server</th>
                                    <th>Notebook</th>
                                    <th>Python</th>
                                </tr>
                                <tr>
                                    <td>GP Prod</td>
                                    <td>{weekly_jobs['prod']}</td>
                                    <td>{weekly_jobs['prod-py']}</td>
                                </tr>
                                <tr>
                                    <td>GP Broad</td>
                                    <td>{weekly_jobs['broad']}</td>
                                    <td>{weekly_jobs['broad-py']}</td>
                                </tr>
                                <tr>
                                    <td>GP IU</td>
                                    <td>{weekly_jobs['iu']}</td>
                                    <td>{weekly_jobs['iu-py']}</td>
                                </tr>
                                <tr>
                                    <td>GP Cloud</td>
                                    <td>{weekly_jobs['aws']}</td>
                                    <td>{weekly_jobs['aws-py']}</td>
                                </tr>
                            </table>

                            <h3>Jobs run since 2016-08-07</h3>
                            <table border="1">
                                <tr>
                                    <th>Server</th>
                                    <th>Notebook</th>
                                    <th>Python</th>
                                </tr>
                                <tr>
                                    <td>GP Prod</td>
                                    <td>{total_jobs['prod']}</td>
                                    <td>{total_jobs['prod-py']}</td>
                                </tr>
                                <tr>
                                    <td>GP Broad</td>
                                    <td>{total_jobs['broad']}</td>
                                    <td>{total_jobs['broad-py']}</td>
                                </tr>
                                <tr>
                                    <td>GP IU</td>
                                    <td>{total_jobs['iu']}</td>
                                    <td>{total_jobs['iu-py']}</td>
                                </tr>
                                <tr>
                                    <td>GP Cloud</td>
                                    <td>{total_jobs['aws']}</td>
                                    <td>{total_jobs['aws-py']}</td>
                                </tr>
                            </table>

                            <h3>DockerHub stats</h3>
                            <table border="1">
                                <tr>
                                    <th>Image</th>
                                    <th>Stars</th>
                                    <th>Pulls</th>
                                </tr>
                                <tr>
                                    <td>gp-notebook</td>
                                    <td>{docker['notebook']['stars']}</td>
                                    <td>{docker['notebook']['pulls']}</td>
                                </tr>
                                <tr>
                                    <td>gp-jupyterhub (retired)</td>
                                    <td>{docker['jupyterhub']['stars']}</td>
                                    <td>{docker['jupyterhub']['pulls']}</td>
                                </tr>
                            </table>
            """

    body = body + f"""
                            {top_tools_table(event_stats)}
    
                            {updated_notebooks_table(nb_updates)}

                            {top_notebooks_table(nb_usage)}

                            {top_disk_table(user_disk)}

                        </td>
                    </tr>
                </table>
            </body>
        </html>
    """

    msg.attach(MIMEText(body, 'html'))

    server = smtplib.SMTP(MAIL_SERVER, 25)
    server.login(MAIL_USERNAME, MAIL_PASSWORD)
    text = msg.as_string()
    server.sendmail(fromaddr, toaddr.split(', '), text)
    server.quit()


def gather_stats():
    # Make necessary calls
    disk = get_disk_usage()
    nb_count = get_nb_count()
    users = get_users()
    logins = get_logins()
    nb_updates = get_nb_updates()
    nb_usage = get_nb_usage()
    user_disk = get_user_disk()
    event_stats = get_event_stats(datetime.now() - timedelta(days=7))

    if include_extension:
        weekly_jobs = get_weekly_jobs()
        docker = get_docker()
        total_jobs = get_total_jobs(weekly_jobs)
    else:
        weekly_jobs, docker, total_jobs = None, None, None

    # Send the email
    send_mail(users, logins, disk, nb_count, weekly_jobs, docker, total_jobs, nb_updates, nb_usage, user_disk, event_stats)


gather_stats()
