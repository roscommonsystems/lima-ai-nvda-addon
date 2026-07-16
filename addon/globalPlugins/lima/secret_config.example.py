# -*- coding: UTF-8 -*-
# Template for secret_config.py (which is gitignored, so it is not in the repo).
#
# Each developer creates their own secret_config.py locally:
#   1. Copy this file to "secret_config.py" in this same folder.
#   2. Fill in the four values from your Google Cloud / Firebase consoles:
#        * GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
#            Google Cloud console -> APIs & Services -> Credentials ->
#            OAuth client ID of type "Desktop app".
#        * FIREBASE_API_KEY
#            Firebase console -> Project settings -> your Web app -> "apiKey".
#        * FIREBASE_PROJECT_ID
#            Firebase console -> Project settings -> "Project ID".
#
# firebase_config.py reads these values. Without secret_config.py, the add-on
# still loads but sign-in stays disabled (is_configured() returns False).
# Never commit your filled-in secret_config.py.

GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""
FIREBASE_API_KEY = ""
FIREBASE_PROJECT_ID = ""
