from jupyterhub.services.auth import HubOAuthenticated, HubOAuthCallbackHandler, HubAuth
from tornado.ioloop import IOLoop
from tornado.web import Application, RequestHandler, authenticated
import logging
import globus_sdk
import json
import os
import threading
import time


# Read environment variables and set constants
JUPYTERHUB_API_TOKEN = os.getenv("JUPYTERHUB_API_TOKEN")
COLLECTION_ID = os.getenv("GLOBUS_COLLECTION_ID") or os.getenv("GLOBUS_LOCAL_ENDPOINT")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")


class AuthError(Exception):
    """Raised on failure to authorize a valid Globus or Hub user"""
    pass


class GlobusUser:
    """Handles verification of Globus user tokens and provides a transfer client for
       starting transfers on behalf of users"""

    def __init__(self, handler):
        auth_client = globus_sdk.ConfidentialAppAuthClient(CLIENT_ID, CLIENT_SECRET)
        self.handler = handler
        self.token = self.get_token()
        self.introspection_data = self.introspect(auth_client, self.token)
        self.dependent_tokens = auth_client.oauth2_get_dependent_tokens(self.token)

    @property
    def username(self): return self.introspection_data["username"]

    @property
    def id(self): return self.introspection_data["sub"]

    def get_token(self):
        """Supports Globus tokens retrieved either from the Authorization header or
           from the globus_token property in the request body"""
        token = None

        try:
            data = self.handler.json_data
            if data.get("globus_token"): token = data["globus_token"]
        except KeyError:
            if "Authorization" in self.handler.request.headers:
                token = self.handler.request.headers["Authorization"].split(1)
        if token is None: raise AuthError('Token missing')
        return token

    @staticmethod
    def introspect(auth_client, token):
        introspection = auth_client.oauth2_token_introspect(token)
        if introspection.get("active") is False: raise AuthError("Token is not active")
        expires_in = introspection["exp"] - time.time()
        if expires_in < 0: raise AuthError("Globus token has expired")
        return introspection.data

    def get_transfer_client(self):
        authorizer = globus_sdk.AccessTokenAuthorizer(self.dependent_tokens[0]["access_token"])
        return globus_sdk.TransferClient(authorizer=authorizer)


class ACLManager:
    """Provides a service for setting ACLs and tracking them throughout the life
    of the Globus transfer"""
    cache = {}

    def __init__(self):
        self.transfer_client = ACLManager.get_app_transfer_client()
        threading.Thread(target=self.worker, daemon=True).start()

    @staticmethod
    def get_app_transfer_client():
        """Authorize and return a Globus transfer client"""
        auth_client = globus_sdk.ConfidentialAppAuthClient(CLIENT_ID, CLIENT_SECRET)
        tokens = auth_client.oauth2_client_credentials_tokens(
            requested_scopes=globus_sdk.TransferClient.scopes.all).data
        authorizer = globus_sdk.AccessTokenAuthorizer(tokens["access_token"])
        return globus_sdk.TransferClient(authorizer=authorizer)

    class ACLGroup:
        """Helper class to track ACLs according to user transfers."""

        def __init__(self, acl_id, path, tasks):
            self.acl_id = acl_id
            self.path = path
            self.tasks = tasks

        def check_transfers(self, transfer_client):
            for task in self.tasks:
                if transfer_client.get_task(task)["status"] in ["SUCCEEDED", "FAILED"]:
                    self.tasks.remove(task)

    @staticmethod
    def worker():
        """Worker thread for tracking Globus transfers"""
        while True:
            for uid, data in ACLManager.cache.items():
                user = data["user"]
                user_tc = user.get_transfer_client()
                for path in list(data["paths"]):
                    acl_obj = data["paths"][path]
                    acl_obj.check_transfers(user_tc)
                    if not acl_obj.tasks:
                        app_tc = ACLManager.get_app_transfer_client()
                        app_tc.delete_endpoint_acl_rule(COLLECTION_ID, acl_obj.acl_id)
                        del data["paths"][path]

            for uid in list(ACLManager.cache):
                if not ACLManager.cache[uid]["paths"]:
                    del ACLManager.cache[uid]

            time.sleep(1)

    def track_acl(self, user, transfer_task_id, path, acl_id):
        """Track the ACL"""
        if not ACLManager.cache.get(user.id):
            ACLManager.cache[user.id] = {
                "user": user,
                "paths": {},
            }
        if ACLManager.cache[user.id]["paths"].get(path):
            ACLManager.cache[user.id]["paths"][path].tasks.append(transfer_task_id)
        else:
            ACLManager.cache[user.id] = {
                "user": user,
                "paths": {path: self.ACLGroup(acl_id, path, [transfer_task_id])},
            }

    @staticmethod
    def get_acl_path(transfer_doc):
        """Given a transfer doc, fetch the path the user would need access"""
        if transfer_doc["source_endpoint"] == COLLECTION_ID: key = "source_path"
        elif transfer_doc["destination_endpoint"] == COLLECTION_ID: key = "destination_path"
        else: raise ValueError(f"Transfer does not use hub collection {COLLECTION_ID}")

        paths = { f'/{os.path.dirname(d[key])}/' for d in transfer_doc["DATA"] }
        if len(paths) > 1: raise ValueError("Complex transfers are not supported!")
        path = list(paths)[0]
        return path or "/"

    @staticmethod
    def set_user_acl(globus_user, acl_path):
        """Set an ACL for the user, return the ACL's ID"""
        app_tc = ACLManager.get_app_transfer_client()
        try:
            response = app_tc.add_endpoint_acl_rule(
                COLLECTION_ID,
                rule_data = {
                    "DATA_TYPE": "access",
                    "principal_type": "identity",
                    "principal": globus_user.id,
                    "path": acl_path,
                    "permissions": "rw",
                },
            )
            return response["access_id"]
        except globus_sdk.TransferAPIError as tapie:
            if tapie.code == "Exists":
                for acl in app_tc.endpoint_acl_list(COLLECTION_ID):
                    if acl["path"] == acl_path and acl["principal"] == globus_user.id: return acl["id"]
            else: raise Exception(f"Unknown error for {globus_user.username}")
        raise Exception(f"Unable to make/find ACL for user {globus_user.username} at {acl_path}")


class GlobusHandler(HubOAuthenticated, RequestHandler):
    """Endpoint for submitting Globus transfer requests and handling ACL management"""

    def set_default_headers(self):
        """Handle CORS requests"""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, PUT, GET, OPTIONS, DELETE')

    def options(self):
        """Special handling for OPTIONS requests"""
        self.set_status(204)
        self.finish()

    def prepare(self):
        """Prepare requests returning JSON data by parsing it ahead of time"""
        super(GlobusHandler, self).prepare()
        try: self.json_data = json.loads(self.request.body)
        except json.JSONDecodeError: self.json_data = None
        except TypeError: self.json_data = None

    def get_globus_user(self):
        try:
            token = self.request.headers["Authorization"].split()[1]
            hub_user = hub_auth.user_for_token(token)
            if hub_user is None: raise AuthError('Unable to validate hub user')
            return GlobusUser(self)
        except AuthError as exc:
            self.send_error(401, reason='Failed to authorize')
            return None

    @staticmethod
    def do_transfer(user, transfer_document):
        """Do the actual user transfer and return the transfer response."""
        user_tc = user.get_transfer_client()
        td = globus_sdk.TransferData(user_tc,
                                     transfer_document["source_endpoint"],
                                     transfer_document["destination_endpoint"])
        for transfer_item in transfer_document["DATA"]:
            td.add_item(transfer_item["source_path"],
                        transfer_item["destination_path"],
                        recursive=transfer_item["recursive"])
        return user_tc.submit_transfer(td).data

    @authenticated
    def get(self):
        """Returns info to make sure the service is working properly"""
        self.write({
            "service": "Globus Service",
            "description": "This service allows transferring data to a shared Globus collection",
            "collection": COLLECTION_ID,
            "hub_user": self.get_current_user()
        })
        self.finish()

    def post(self):
        """Accept a post request from globus-jupyterlab.
           Sets ACLs and initiates the transfer."""

        # Obtain the globus user and the transfer doc
        globus_user = self.get_globus_user()
        transfer_doc = self.json_data["transfer"]

        # Set the ACL and initiate the transfer
        try:
            acl_path = acl_manager.get_acl_path(transfer_doc)                           # Get the path to set
            acl_id = acl_manager.set_user_acl(globus_user, acl_path)                    # Set the ACL
            response = self.do_transfer(globus_user, transfer_doc)                      # Start the transfer
            acl_manager.track_acl(globus_user, response["task_id"], acl_path, acl_id)   # Track the transfer
            self.set_status(201)
            self.write(response)
        except KeyError:
            self.send_error(400, reason="Invalid Transfer Document")
        except globus_sdk.TransferAPIError as tapie:
            self.send_error(tapie.http_status, reason=tapie.raw_json)
        self.finish()


# Create manager singletons
hub_auth = HubAuth(api_token=JUPYTERHUB_API_TOKEN, cache_max_age=60)
acl_manager = ACLManager()


def make_app():
    """Assign handlers to the URLs and return the Tornado app"""
    urls = [
        (r"/services/globus/", GlobusHandler),
        (r"/services/globus/oauth_callback", HubOAuthCallbackHandler),]
    return Application(urls, cookie_secret=os.urandom(32), debug=True)


if __name__ == '__main__':
    logging.info(f'Globus Endpoint Management started on 3004')

    app = make_app()
    app.listen(3004)
    IOLoop.instance().start()
