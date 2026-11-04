from typing import ClassVar

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

from shop.models import Address, DeliveryZone

from .models import User


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")

    def clean_email(self) -> str:
        email = str(self.cleaned_data["email"]).strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already uses this email address.")
        return email


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name")


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ("label", "recipient", "phone", "line", "locality", "postcode", "zone")
        labels: ClassVar = {"line": "Street address", "zone": "Delivery zone"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        zone = self.fields["zone"]
        assert isinstance(zone, forms.ModelChoiceField)
        zone.queryset = DeliveryZone.objects.filter(active=True)
