# Dockerfile for running an instance of the g2nb Notebook Repository

# Pull a known good jupyterhub image from the official Jupyter stacks
# Built 05-06-2022
FROM jupyterhub/jupyterhub:2.3.1

MAINTAINER Thorin Tabor <tmtabor@cloud.ucsd.edu>

#############################################
##      System updates                     ##
#############################################

RUN apt-get update && apt-get install -y gconf-service libasound2 libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 libexpat1 \
    libfontconfig1 libgcc1 libgconf-2-4 libgdk-pixbuf2.0-0 libglib2.0-0 libgtk-3-0 libnspr4 libpango-1.0-0 libpangocairo-1.0-0 \
    libstdc++6 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 \
    libxrender1 libxss1 libxtst6 ca-certificates fonts-liberation libappindicator1 libnss3 lsb-release xdg-utils wget nano \
    docker.io libcurl4 curl gcc python3-dev libmysqlclient-dev \
    && pip install awscli jupyterhub_idle_culler sqlalchemy tornado jinja2 traitlets requests pymysql oauthenticator \
    dockerspawner globus-sdk \
    && ln -s /usr/bin/python3 /usr/bin/python

#############################################
##      Create the data volume             ##
#############################################

RUN mkdir /data

#############################################
##      Force builds with new releases     ##
#############################################

RUN echo '22.08.1, Globus update'

#############################################
##      Add the repositories               ##
#############################################

RUN git clone https://github.com/g2nb/multiauthenticator.git /srv/multiauthenticator/
RUN git clone https://github.com/genepattern/gpauthenticator.git /srv/gpauthenticator/
RUN git clone https://github.com/g2nb/workspace.git /srv/workspace/
RUN git clone https://github.com/g2nb/hub-theme.git /srv/hub-theme/
RUN git clone https://github.com/g2nb/notebook-projects.git /srv/notebook-projects/

#############################################
##      Configure the repository           ##
#############################################

# Create subdirectories in the data directory
RUN mkdir /data/repository
RUN mkdir /data/users
RUN mkdir /data/shared
RUN mkdir /data/defaults

#############################################
##      Install Authenticator & Services   ##
#############################################

# Add to the PYTHONPATH
RUN cp -r /srv/notebook-projects/projects /usr/local/lib/python3.8/dist-packages/
RUN mv /srv/gpauthenticator/gpauthenticator /usr/local/lib/python3.8/dist-packages/
RUN mv /srv/multiauthenticator/multiauthenticator.py /usr/local/lib/python3.8/dist-packages/

# Add static assets to JupyterHub
RUN cp /srv/notebook-projects/static/js/* /usr/local/share/jupyterhub/static/js/
RUN cp /srv/notebook-projects/static/css/* /usr/local/share/jupyterhub/static/css/

#############################################
##      Add the config files               ##
#############################################

COPY ./config/jupyterhub_config.py /data/
COPY ./config/projects_config.py /data/

#############################################
##      Add the GenePattern theme          ##
#############################################

# Add the theme assets to JupyterHub
RUN cp /srv/hub-theme/theme/images/* /usr/local/share/jupyterhub/static/images/
RUN cp /srv/hub-theme/theme/css/* /usr/local/share/jupyterhub/static/css/

#############################################
##  $NB_USER                               ##
##      Enable nano and vi                 ##
#############################################

ENV TERM xterm

#############################################
##      Start JupyterHub                   ##
#############################################

CMD ["jupyterhub", "-f", "/data/jupyterhub_config.py"]