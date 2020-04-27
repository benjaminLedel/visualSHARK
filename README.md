About
=====
The visualSHARK is a graphical frontend for the MongoDB of the SmartSHARK project.
It consists of a Django based Backend and a VueJS based Frontend.
Some functionality relies on a worker process which executes background tasks and a Websocket connection.


Requirements
============

Requirements and how to get them with Ubuntu 16.04 LTS.
RabbitMQ has to be running with activated web_stomp module.

Python 3.6
----------
```bash
add-apt-repository ppa:jonathonf/python-3.6
apt-get update
apt-get install python3.6
apt-get install python3.6-dev
apt-get install python3.6-venv
```

python-3.6 uwsgi module (only for production deployment)
--------------------------------------------------------
```bash
apt-get install python3.6 python3.6-dev uwsgi uwsgi-src uuid-dev libcap-dev libpcre3-dev libssl-dev
cd ~
PYTHON=python3.6 uwsgi --build-plugin "/usr/src/uwsgi/plugins/python python36"
mv python36_plugin.so /usr/lib/uwsgi/plugins/python36_plugin.so
chmod 644 /usr/lib/uwsgi/plugins/python36_plugin.so
```

pygraphviz
----------
```bash
apt-get install graphviz-dev
cd /srv/www/visualSHARK
source bin/activate
pip install pygraphviz --install-option="--include-path=/usr/include/graphviz" --install-option="--library-path=/usr/lib/graphviz/"
```

NPM
---
```bash
cd ~
curl -sL https://deb.nodesource.com/setup_8.x -o nodesource_setup.sh
nano nodesource_setup.sh
bash nodesource_setup.sh
apt-get install nodejs
```

RabbitMQ
--------
```bash
apt-get install rabbitmq-server
systemctl start rabbitmq-server
rabbitmq-plugins enable rabbitmq_web_stomp
rabbitmq-plugins enable rabbitmq_management
```


Installation
============

Install Backend
---------------

```bash
apt-get install libmysqlclient-dev
git clone https://github.com/smartshark/visualSHARK.git

cd /srv/www/visualSHARK
python3.6 -m venv .
source bin/activate
pip install -r requirements.txt

# change database credentials for MySQL DB and Mongo DB
# change secret key and, if ServerSHARK is available, URL to the endpoint and an api key.
cp sntest/settings_dist.py sntest/settings.py
nano sntest/settings.py

# migrate database
python manage.py migrate

# create superuser
python manage.py createsuperuser
```

Install Frontend
----------------

```bash
cd /srv/www/visualSHARK/frontend/app

# install dependencies
npm install

# install patch-package and apply patches for MonacoEditor
npm install patch-package
npx patch-pacakge

# change local production settings, endpoints for RabbitMQ (websocket) and visualSHARK backend
cp env.production.local .env.production.local
nano .env.production.local

# run frontend in dev mode
# npm run serve

# build prod version
npm run build
```


Operation
=========

run backend in dev mode
```bash
cd /srv/www/visualSHARK
source bin/activate
python manage runserver
```

run backend worker
```bash
cd /srv/www/visualSHARK
source bin/activate
python manage peon
```

run frontend in dev mode
```bash
cd /srv/www/visualSHARK/frontend/app
npm run dev
```
