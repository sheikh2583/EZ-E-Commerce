from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from shop.models import Address, DeliveryZone


class Accounts(TestCase):
    password = "Long-test-passphrase-for-account"

    def test_registration_normalizes_email_and_hashes_password(self):
        data = {
            "email": "Shopper@Example.test", "first_name": "Alex", "last_name": "Guest",
            "password1": self.password, "password2": self.password,
        }
        self.assertRedirects(self.client.post(reverse("register"), data), reverse("account"))
        user = User.objects.get()
        self.assertEqual(user.email, "shopper@example.test")
        self.assertTrue(user.password.startswith("argon2"))
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff)
        self.assertContains(self.client.get(reverse("account")), user.email)
        self.client.logout()
        self.assertContains(self.client.post(reverse("register"), data), "already uses this email")
        self.assertEqual(User.objects.count(), 1)

    def test_login_rejects_invalid_password_and_external_redirect(self):
        user = User.objects.create_user("customer@example.test", self.password)
        self.assertContains(self.client.post(reverse("login"), {
            "username": user.email, "password": "bad",
        }), "Please enter a correct")
        self.assertNotIn("_auth_user_id", self.client.session)
        session = self.client.session
        session["guest_data"] = "retained"
        session.save()
        initial_session_key = session.session_key
        self.assertRedirects(self.client.post(reverse("login"), {
            "username": "Customer@Example.test", "password": self.password, "next": "https://other.example/",
        }), reverse("account"))
        self.assertNotEqual(self.client.session.session_key, initial_session_key)
        self.assertEqual(self.client.session["guest_data"], "retained")
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_profile_and_addresses_are_scoped_to_owner(self):
        user = User.objects.create_user("customer@example.test", self.password)
        other = User.objects.create_user("other@example.test", self.password)
        other_address = Address.objects.create(user=other, label="Private")
        zone = DeliveryZone.objects.create(name="Inside Dhaka", code="dhaka", fee=8000)
        self.client.force_login(user)
        self.assertRedirects(self.client.post(reverse("account"), {"first_name": "Alex"}), reverse("account"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Alex")
        data = {
            "label": "Home", "recipient": "Alex", "phone": "+8801700000000",
            "line": "8 Example Lane", "locality": "Dhaka", "zone": zone.pk,
        }
        self.assertRedirects(self.client.post(reverse("address_add"), data), reverse("account"))
        address = Address.objects.get(user=user)
        self.assertContains(self.client.get(reverse("account")), "8 Example Lane")
        self.assertNotContains(self.client.get(reverse("account")), "Private")
        self.assertEqual(self.client.post(reverse("address_edit", args=[other_address.pk]), data).status_code, 404)
        self.assertEqual(self.client.post(reverse("address_delete", args=[other_address.pk])).status_code, 404)
        self.assertRedirects(self.client.post(reverse("address_edit", args=[address.pk]), {
            **data, "label": "Office",
        }), reverse("account"))
        self.assertRedirects(self.client.post(reverse("address_delete", args=[address.pk])), reverse("account"))
        self.assertFalse(Address.objects.filter(pk=address.pk).exists())

    def test_staff_route_requires_staff_flag_and_a_store_permission(self):
        call_command("setup_roles", stdout=StringIO())
        role = Group.objects.get(name="Fulfillment")
        user = User.objects.create_user("customer@example.test", self.password)
        self.assertRedirects(self.client.get(reverse("staff")), f"{reverse('login')}?next={reverse('staff')}")
        self.client.force_login(user)
        user.groups.add(role)
        self.assertEqual(self.client.get(reverse("staff")).status_code, 403)
        user.groups.clear()
        user.is_staff = True
        user.save()
        self.assertEqual(self.client.get(reverse("staff")).status_code, 403)
        user.groups.add(role)
        self.assertContains(self.client.get(reverse("staff")), "Store management")

    def test_csrf_protects_login_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        user = User.objects.create_user("customer@example.test", self.password)
        self.assertEqual(client.post(reverse("login"), {"username": user.email}).status_code, 403)
        client.force_login(user)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
