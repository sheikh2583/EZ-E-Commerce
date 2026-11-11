import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


DEBUG = os.getenv("DJANGO_DEBUG") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
secret_seed = os.getenv("DJANGO_SECRET_SEED", "")
if not SECRET_KEY and len(secret_seed) >= 43:
    SECRET_KEY = hashlib.sha512(secret_seed.encode()).hexdigest()
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
if render_host and render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if not SECRET_KEY or (not DEBUG and len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (at least 50 characters outside debug mode).")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS.")

DATABASES = {
    "default": dj_database_url.config(conn_max_age=0 if DEBUG else 60, conn_health_checks=True)
}
if DATABASES["default"].get("ENGINE") != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Set DATABASE_URL to a PostgreSQL connection URL.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "storefront",
    "shop",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "shop.security.SecurityBoundary",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "shop.cart.cart_indicator",
            ],
        },
    }
]
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{validator}"}
    for validator in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]
LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Dhaka"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": (
        "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )},
}
SECURE_SSL_REDIRECT = not DEBUG
SECURE_REDIRECT_EXEMPT = [r"^(?:healthz|readyz)$"]
if os.getenv("DJANGO_TRUST_HTTPS_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
try:
    DJANGO_FORWARDED_FOR_HOPS = int(os.getenv("DJANGO_FORWARDED_FOR_HOPS", "0"))
except ValueError as error:
    raise ImproperlyConfigured("Set DJANGO_FORWARDED_FOR_HOPS to an integer from 0 to 5.") from error
if not 0 <= DJANGO_FORWARDED_FOR_HOPS <= 5:
    raise ImproperlyConfigured("Set DJANGO_FORWARDED_FOR_HOPS to an integer from 0 to 5.")
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "{asctime} {levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "root": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
}

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "account"
LOGOUT_REDIRECT_URL = "home"

PAYMENT_MODE = os.getenv("PAYMENT_MODE", "disabled")
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "sslcommerz")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
SSLCOMMERZ_STORE_ID = os.getenv("SSLCOMMERZ_STORE_ID", "")
SSLCOMMERZ_STORE_PASSWORD = os.getenv("SSLCOMMERZ_STORE_PASSWORD", "")
LCT_API_KEY = os.getenv("LCT_API_KEY", "")
LCT_ONE_TIME_GRANT_ID = os.getenv("LCT_ONE_TIME_GRANT_ID", "")
LCT_CHECKOUT_PROVIDER = os.getenv("LCT_CHECKOUT_PROVIDER", "sslcommerz")
LCT_MERCHANT_ID = os.getenv("LCT_MERCHANT_ID", "")
LCT_WEBHOOK_SECRET = os.getenv("LCT_WEBHOOK_SECRET", "")
if PAYMENT_MODE not in {"disabled", "simulation", "sandbox", "live"}:
    raise ImproperlyConfigured("Select a supported PAYMENT_MODE.")
if PAYMENT_PROVIDER not in {"pap", "sslcommerz"}:
    raise ImproperlyConfigured("Select a supported PAYMENT_PROVIDER.")
if PAYMENT_MODE == "simulation" and not DEBUG:
    raise ImproperlyConfigured("Payment simulation requires debug mode.")
if PAYMENT_MODE in {"sandbox", "live"}:
    if not PUBLIC_BASE_URL:
        raise ImproperlyConfigured("Set a public HTTPS base URL for gateway callbacks.")
    if PAYMENT_MODE == "live" and DEBUG:
        raise ImproperlyConfigured("Live payments require production settings.")
    if PAYMENT_PROVIDER == "pap":
        if not re.fullmatch(rf"sk_{PAYMENT_MODE}_[!-~]+", LCT_API_KEY):
            raise ImproperlyConfigured("Set an LCT_API_KEY for the selected payment mode.")
        try:
            LCT_ONE_TIME_GRANT_ID = str(UUID(LCT_ONE_TIME_GRANT_ID))
            LCT_MERCHANT_ID = str(UUID(LCT_MERCHANT_ID))
        except ValueError:
            raise ImproperlyConfigured("Set valid LCT_ONE_TIME_GRANT_ID and LCT_MERCHANT_ID UUIDs.") from None
        if not re.fullmatch(r"whsec_[A-Za-z0-9+/]{43}=", LCT_WEBHOOK_SECRET):
            raise ImproperlyConfigured("Set a valid LCT_WEBHOOK_SECRET.")
        if LCT_CHECKOUT_PROVIDER not in {"stripe", "sslcommerz"}:
            raise ImproperlyConfigured("Select a supported LCT_CHECKOUT_PROVIDER.")
        if PAYMENT_MODE == "live" and LCT_CHECKOUT_PROVIDER == "sslcommerz":
            raise ImproperlyConfigured("PAP documents SSLCOMMERZ Checkout for sandbox only.")
    elif not SSLCOMMERZ_STORE_ID or not SSLCOMMERZ_STORE_PASSWORD:
        raise ImproperlyConfigured("Set SSLCOMMERZ credentials for the selected mode.")

if PUBLIC_BASE_URL:
    public_origin = urlsplit(PUBLIC_BASE_URL)
    if (public_origin.scheme != "https" or not public_origin.hostname
            or public_origin.username or public_origin.password or public_origin.path
            or public_origin.query or public_origin.fragment):
        raise ImproperlyConfigured("PUBLIC_BASE_URL must be an HTTPS origin.")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
if any((CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)) and not all(
    (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)
):
    raise ImproperlyConfigured("Set all Cloudinary configuration values together.")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "")
MIMSMS_API_KEY = os.getenv("MIMSMS_API_KEY", "")
MIMSMS_USERNAME = os.getenv("MIMSMS_USERNAME", "")
MIMSMS_SENDER = os.getenv("MIMSMS_SENDER", "")
NOTIFICATION_ADMIN_EMAIL = os.getenv("NOTIFICATION_ADMIN_EMAIL", "")
NOTIFICATION_ADMIN_PHONE = os.getenv("NOTIFICATION_ADMIN_PHONE", "")
