from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from tornado.web import Application, RequestHandler
from tornado.ioloop import IOLoop
import logging


Base = declarative_base()
DB_PATH = '//data/usage.sqlite'  # '//Users/tmtabor/workspace/workspace/usage.sqlite'


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
        data = { c.name: getattr(self, c.name) for c in self.__table__.columns }
        for k in data:
            if isinstance(data[k], datetime): data[k] = str(data[k])  # Special case for datetimes
        return data

    def get(event_token=None):
        # Query the database
        session = Database.instance().Session()
        query = session.query(UsageEvent)
        if event_token is not None: query = query.filter(UsageEvent.event_token == event_token)
        results = query.all()
        session.close()
        return results


class UsageHandler(RequestHandler):
    """Endpoint for tracking g2nb usage"""

    def set_default_headers(self):
        """Handle CORS requests"""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, PUT, GET, OPTIONS, DELETE')

    def options(self):
        self.set_status(204)
        self.finish()

    def get(self, event_token=None):
        """Record usage events and return an OK response"""

        # Cap the event_token at 128 characters
        event_token = event_token[:128]

        # Get the optional description if included, cap at 256 characters
        description = self.request.body[:256].decode('UTF-8') or None

        # Write the event_token and description to the database
        UsageEvent(event_token=event_token, description=description).save()

        # Return a basic response
        self.write('OK')
        self.finish()

    def post(self, event_token=None):
        """Record usage events and return an OK response"""
        return self.get(event_token=event_token)


class ReportHandler(RequestHandler):
    """Endpoint for reporting g2nb usage"""

    def set_default_headers(self):
        """Handle CORS requests"""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, PUT, GET, OPTIONS, DELETE')

    def options(self):
        self.set_status(204)
        self.finish()

    def get(self, event_token=None):
        """List usage events in JSON format"""
        results = UsageEvent.get()
        events = [e.json() for e in results]
        self.write({'events': events})
        self.finish()


def make_app():
    # Assign handlers to the URLs and return
    urls = [(r"/services/usage/report/", ReportHandler),
            (r"/services/usage/(?P<event_token>.*)/", UsageHandler)]
    return Application(urls, debug=True)


if __name__ == '__main__':
    logging.info(f'Usage Tracking Service started on 3003')

    app = make_app()
    app.listen(3003)
    IOLoop.instance().start()