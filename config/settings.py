import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.getenv("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = [
    "config.apps.ContestAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "contests",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ["POSTGRES_DB"],
    "USER": os.environ["POSTGRES_USER"],
    "PASSWORD": os.environ["POSTGRES_PASSWORD"],
    "HOST": os.getenv("POSTGRES_HOST", "localhost"),
    "PORT": os.getenv("POSTGRES_PORT", "5432"),
    "CONN_MAX_AGE": 0,
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation." + name}
    for name in [
        "UserAttributeSimilarityValidator", "MinimumLengthValidator",
        "CommonPasswordValidator", "NumericPasswordValidator",
    ]
]
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_ON_SUCCESS = True
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("UNIVERSITY_TIMEZONE", "Asia/Baku")
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
HTTPS = os.getenv("HTTPS", "True") == "True"
SECURE_SSL_REDIRECT = HTTPS
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_HSTS_SECONDS = 31536000 if HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS
SECURE_HSTS_PRELOAD = HTTPS
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200
MAX_SOURCE_BYTES = 64 * 1024
MAX_TEST_BYTES = 1024 * 1024
MAX_CONTEST_TEST_BYTES = 64 * 1024 * 1024
SUBMISSION_INTERVAL_SECONDS = 15
SUBMISSION_HOURLY_LIMIT = 100
JUDGE_ENABLED = os.getenv("JUDGE_ENABLED", "False") == "True"
JUDGE_ISOLATE = os.getenv("JUDGE_ISOLATE", "/usr/local/bin/isolate")
JUDGE_BOX_ID = int(os.getenv("JUDGE_BOX_ID", "0"))
JUDGE_LEASE_SECONDS = 90
JUDGE_MAX_ATTEMPTS = 3
JUDGE_OUTPUT_BYTES = 1024 * 1024
JUDGE_ROOTFS = os.getenv("JUDGE_ROOTFS", "/srv/judge-root")
JUDGE_LOCK_DIR = os.getenv("JUDGE_LOCK_DIR", "/var/lib/university-judge")
JUDGE_COMPILE_SECONDS = 20
JUDGE_COMPILE_MEMORY_MB = 512
JUDGE_COMPILE_FILE_KB = 16384
JUDGE_DISK_BLOCKS = 65536
JUDGE_DISK_INODES = 256

REQUIRE_ADMIN_MFA = not DEBUG
OTP_TOTP_ISSUER = "University Contest Judge"
OTP_ADMIN_HIDE_SENSITIVE_DATA = True
DATABASES["default"]["OPTIONS"] = {
    "sslmode": os.getenv("POSTGRES_SSLMODE", "prefer"),
}
if os.getenv("POSTGRES_SSLROOTCERT"):
    DATABASES["default"]["OPTIONS"]["sslrootcert"] = os.environ["POSTGRES_SSLROOTCERT"]
JUDGE_PYTHON_TIME_MULTIPLIER = float(os.getenv("JUDGE_PYTHON_TIME_MULTIPLIER", "3"))
# Set only when Gunicorn is loopback-only behind the supplied trusted proxy.
if os.getenv("TRUST_HTTPS_PROXY", "False") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
