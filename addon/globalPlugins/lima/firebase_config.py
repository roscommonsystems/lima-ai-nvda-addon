# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: Firebase / Google OAuth configuration.
#
# The four project values (client id/secret, API key, project id) are NOT kept
# here. They live in secret_config.py, which is gitignored so the secrets stay
# out of git. Create that file locally (see the four names below) from your
# Google Cloud / Firebase consoles. For a desktop OAuth client none of these are
# truly confidential, but keeping them out of the repo is good hygiene.
#
# Also required in the consoles (no code change needed):
#   * Firebase -> Authentication -> Sign-in method -> enable Google.
#   * Firestore rule so each user can only write their own doc:
#       match /users/{uid} { allow read, write: if request.auth.uid == uid; }

try:
	from . import secret_config
	GOOGLE_CLIENT_ID = secret_config.GOOGLE_CLIENT_ID
	GOOGLE_CLIENT_SECRET = secret_config.GOOGLE_CLIENT_SECRET
	FIREBASE_API_KEY = secret_config.FIREBASE_API_KEY
	FIREBASE_PROJECT_ID = secret_config.FIREBASE_PROJECT_ID
except ImportError:
	# No secret_config.py present; sign-in stays disabled (is_configured()
	# returns False) rather than breaking the add-on load.
	GOOGLE_CLIENT_ID = GOOGLE_CLIENT_SECRET = FIREBASE_API_KEY = FIREBASE_PROJECT_ID = ""

# Firestore database id (not secret). Use "(default)" unless the project uses a
# named database (Firebase console -> Firestore -> the database's id). This
# product has its own dedicated database, so user docs are flat.
FIREBASE_DATABASE_ID = "lima-nvda-addon-firestore-db"

# Firestore collection holding per-user docs. MUST match the auth server's
# USERS_COLLECTION so the sign-in profile and the server's OpenRouter fields land in the
# SAME document. This is the PROD build -> "users"; the dev build uses "users_dev".
FIRESTORE_USERS_COLLECTION = "users"

# Base URL of the LIMA Cloud Run backend (not secret). All AI calls are proxied
# through it so the OpenRouter key never reaches the client; the add-on authenticates
# each call with the user's Firebase ID token. Confirm the exact URL with:
#   gcloud run services describe lima-addon-auth-server --region us-west1 \
#     --format="value(status.url)"
LIMA_BACKEND_URL = "https://lima-addon-auth-server-423416231887.us-west1.run.app"


def is_configured():
	"""True when the values needed to run sign-in have been injected."""
	return bool(GOOGLE_CLIENT_ID and FIREBASE_API_KEY and FIREBASE_PROJECT_ID)


def get_config():
	"""Return a FirebaseConfig built from the injected values."""
	from . import auth
	return auth.FirebaseConfig(
		GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FIREBASE_API_KEY, FIREBASE_PROJECT_ID,
		FIREBASE_DATABASE_ID or "(default)",
		FIRESTORE_USERS_COLLECTION or "users",
	)
