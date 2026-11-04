from typing import ClassVar

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager["User"]):
    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=email.strip().lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("Superusers require both staff and superuser privileges.")
        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username: str | None) -> "User":
        if username is None:
            raise self.model.DoesNotExist
        return self.get(email__iexact=username.strip())


class User(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []
    objects: ClassVar[UserManager] = UserManager()  # type: ignore[assignment]

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="accounts_unique_email_ci")]

    def clean(self) -> None:
        super().clean()
        self.email = self.email.strip().lower()
