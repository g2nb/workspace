import os
import sys
from gpauthenticator import GenePatternAuthenticator
from oauthenticator.google import GoogleOAuthenticator
from oauthenticator.globus import GlobusOAuthenticator
from projects.hub import UserHandler, PreviewHandler, StatsHandler, pre_spawn_hook, spawner_escape

c = get_config()

#  This is the address on which the proxy will bind. Sets protocol, ip, base_url
c.JupyterHub.bind_url = 'http://:80'

# Listen on all interfaces
c.JupyterHub.hub_ip = '0.0.0.0'
# c.JupyterHub.hub_connect_ip = 'notebook_repository'

# Configure the Authenticator
c.Authenticator.admin_users = ['admin']
c.JupyterHub.authenticator_class = 'multiauthenticator.MultiAuthenticator'
c.MultiAuthenticator.authenticators = [
    (GenePatternAuthenticator, '/genepattern', {
        'service_name': 'GenePattern',
        'users_dir_path': '/data/users',
        'default_nb_dir': '/data/default'
    }),
    (GlobusOAuthenticator, '/globus', {
        'client_id': 'REDACTED',
        'client_secret': 'REDACTED',
        'oauth_callback_url': 'http://localhost:8000/hub/globus/oauth_callback'
    }),
    (GoogleOAuthenticator, '/google', {
        'client_id': 'REDACTED',
        'client_secret': 'REDACTED',
        'oauth_callback_url': 'http://localhost:8000/hub/google/oauth_callback'
    }),
]

# Configure DockerSpawner
c.JupyterHub.spawner_class = 'dockerspawner.DockerSpawner'
c.DockerSpawner.host_ip = '0.0.0.0'
c.DockerSpawner.image = 'g2nb/lab'
c.DockerSpawner.image_whitelist = {
    'Python 3.9': 'g2nb/lab',
    'Legacy': 'genepattern/genepattern-notebook',
}
c.DockerSpawner.escape = spawner_escape
c.DockerSpawner.network_name = 'repo'
c.DockerSpawner.remove_containers = True
c.DockerSpawner.debug = True
c.DockerSpawner.pre_spawn_hook = lambda spawner: pre_spawn_hook(spawner, userdir='/data/users')
c.DockerSpawner.volumes = {
    os.path.join('./data/users/{raw_username}/{servername}'): '/home/jovyan',  # Mount users directory
}

# Add the theme config
c.JupyterHub.logo_file = '/srv/hub-theme/theme/images/g2nb_logo.svg'
c.JupyterHub.template_paths = ['/srv/hub-theme/theme/templates', '/srv/notebook-projects/templates']

# Named server config
c.JupyterHub.allow_named_servers = True
c.JupyterHub.default_url = '/home'
c.JupyterHub.extra_handlers = [('user.json', UserHandler), ('preview', PreviewHandler), ('stats', StatsHandler)]
c.DockerSpawner.name_template = "{prefix}-{username}-{servername}"

# Services API configuration
c.JupyterHub.load_roles = [
    {
        "name": "user",
        "scopes": ["access:services", "self"],  # grant all users access to all services
    },
    {
        "name": "services_default",
        "scopes": [
            "self",
        ],
        "services": ["projects", "sharing", "download", "usage"],
    },
    {
        "name": "jupyterhub-idle-culler-role",
        "scopes": [
            "list:users",
            "read:users:activity",
            "read:servers",
            "delete:servers",
        ],
        "services": ["jupyterhub-idle-culler-service"],
    }
]

c.JupyterHub.services = [
    {
        'name': 'projects',
        'url': 'http://127.0.0.1:3000/',
        'cwd': '/srv/notebook-projects/',
        'oauth_no_confirm': True,
        'environment': {
            'IMAGE_WHITELIST': ','.join(c.DockerSpawner.image_whitelist.keys())
        },
        'command': [sys.executable, 'start-projects.py', '--config=/data/projects_config.py']
    },
    {
        "name": "jupyterhub-idle-culler-service",
        "command": [sys.executable, "-m", "jupyterhub_idle_culler", "--timeout=3600"],
    },
    {
        'name': 'sharing',
        'url': 'http://127.0.0.1:3001/',
        'cwd': '/srv/workspace/scripts',
        'oauth_no_confirm': True,
        'command': [sys.executable, 'redirect_preview.py']
    },
    {
        'name': 'download',
        'url': 'http://127.0.0.1:3002/',
        'cwd': '/srv/workspace/scripts',
        'oauth_no_confirm': True,
        'command': [sys.executable, 'download_endpoint.py']
    },
    {
        'name': 'usage',
        'url': 'http://127.0.0.1:3003/',
        'cwd': '/srv/workspace/scripts',
        'oauth_no_confirm': True,
        'command': [sys.executable, 'usage_endpoint.py']
    },
]

# Enable CORS
origin = '*'
c.Spawner.args = [f'--NotebookApp.allow_origin={origin}', '--NotebookApp.allow_credentials=True',
                  "--NotebookApp.tornado_settings={\"headers\":{\"Referrer-Policy\":\"no-referrer-when-downgrade\"}}"]
c.JupyterHub.tornado_settings = {
    'headers': {
        'Referrer-Policy': 'no-referrer-when-downgrade',
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Credentials': 'true',
    },
}

# Connect to the database in /data
c.JupyterHub.db_url = '/data/jupyterhub.sqlite'

# Write to the log file
c.JupyterHub.extra_log_file = '/data/jupyterhub.log'

# Number of days for a login cookie to be valid. Default is two weeks.
c.JupyterHub.cookie_max_age_days = 1

# File in which to store the cookie secret.
c.JupyterHub.cookie_secret_file = '/srv/jupyterhub/jupyterhub_cookie_secret'

# SSL/TLS will be handled outside of the container
c.JupyterHub.confirm_no_ssl = True

# Grant admin users permission to access single-user servers.
c.JupyterHub.admin_access = True
