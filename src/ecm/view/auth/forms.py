# Copyright (c) 2010-2011 Robin Jarry
#
# This file is part of EVE Corporation Management.
#
# EVE Corporation Management is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# EVE Corporation Management is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# EVE Corporation Management. If not, see <http://www.gnu.org/licenses/>.
import urllib2
import urllib

__date__ = "2011 4 6"
__author__ = "diabeteman"

from django import forms
from django.conf import settings
from django.contrib.auth.models import User, AnonymousUser
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.models import get_current_site
from django.template import loader
from django.utils.http import int_to_base36
from django.template import Context
from django.utils.translation import ugettext_lazy as tr

from captcha.fields import CaptchaField

from ecm.core.eve import api
from ecm.data.common.models import UserAPIKey, UserBinding
from ecm.lib import eveapi
from ecm.data.roles.models import Member
from ecm.view.auth.fields import PasswordField

#------------------------------------------------------------------------------
class AccountCreationForm(forms.Form):

    username = forms.RegexField(label=tr("Username"), max_length=30, regex=r'^[\w.@+-]+$',
                                help_text=tr("Required. Less 30 characters. "
                                          "Letters, digits and @/./+/-/_ only."),
                                error_messages = {'invalid': tr("This field may contain only letters, "
                                                  "numbers and @/./+/-/_ characters.")})
    email = forms.EmailField(label=tr("E-Mail address"))
    password1 = PasswordField(label=tr("Password"), min_length=6)
    password2 = PasswordField(label=tr("Password (confirmation)"), min_length=6,
                                help_text=tr("Enter the same password as above, for verification."))
    keyID = forms.IntegerField(label="API Key ID")
    vCode = forms.CharField(label=tr("Verification Code"),
                            widget=forms.TextInput(attrs={'size':'100'}))
    captcha = CaptchaField()
    characters = []

    def clean_username(self):
        """
        Validate that the username is alphanumeric and is not already in use.
        """
        try:
            User.objects.get(username__iexact=self.cleaned_data['username'])
            raise forms.ValidationError(tr("A user with that username already exists."))
        except User.DoesNotExist:
            return self.cleaned_data['username']

    def clean_email(self):
        """
        Validate that the supplied email address is unique for the site.
        """
        if User.objects.filter(email__iexact=self.cleaned_data['email']):
            raise forms.ValidationError(tr("This email address is already in use."))
        return self.cleaned_data['email']

    def clean_keyID(self):
        """
        Validate that the supplied keyID is not already associated to another User.
        """
        if UserAPIKey.objects.filter(keyID=self.cleaned_data['keyID']):
            raise forms.ValidationError(tr("This EVE account is already registered."))
        return self.cleaned_data['keyID']

    def clean(self):
        cleaned_data = self.cleaned_data

        keyID = cleaned_data.get("keyID")
        vCode = cleaned_data.get("vCode")
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if not None in (keyID, vCode, username, email, password1, password2):
            # test if both password fields match
            if not password1 == password2:
                self._errors["password2"] = self.error_class([tr("Passwords don't match")])
                del cleaned_data["password2"]

            # test if API credentials are valid and if EVE account contains
            # characters which are members of the corporation
            try:
                self.characters = api.get_account_characters(UserAPIKey(keyID=keyID, vCode=vCode))
                valid_account = False
                for c in self.characters:
                    exists = Member.objects.filter(characterID=c.characterID).exists()
                    valid_account |= exists and c.is_corped
                if valid_account:
                    ids = [ c.characterID for c in self.characters ]
                    if Member.objects.filter(characterID__in=ids).exclude(owner=None):
                        self._errors["keyID"] = self.error_class([tr("A character from this account is already registered by another player")])
                        del cleaned_data["keyID"]
                else:
                    self._errors["keyID"] = self.error_class([tr("This EVE account has no character member of the corporation")])
                    del cleaned_data["keyID"]
            except eveapi.Error as e:
                self._errors["keyID"] = self.error_class([str(e)])
                self._errors["vCode"] = self.error_class([str(e)])
                del cleaned_data["keyID"]
                del cleaned_data["vCode"]

        return cleaned_data

#------------------------------------------------------------------------------
class PasswordResetForm(forms.Form):
    email = forms.EmailField(label=tr("E-mail"), max_length=75)
    captcha = CaptchaField()

    def clean_email(self):
        """
        Validates that an active user exists with the given e-mail address.
        """
        email = self.cleaned_data["email"]
        self.users_cache = User.objects.filter(
                                email__iexact=email,
                                is_active=True
                            )
        if len(self.users_cache) == 0:
            raise forms.ValidationError(tr("That e-mail address doesn't have an associated user account. Are you sure you've registered?"))
        return email

    def save(self, domain_override=settings.ECM_BASE_URL, email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=default_token_generator, from_email=None, request=None):
        """
        Generates a one-use only link for resetting password and sends to the user
        """
        from django.core.mail import send_mail
        for user in self.users_cache:
            if not domain_override:
                current_site = get_current_site(request)
                site_name = current_site.name
                domain = current_site.domain
            else:
                site_name = domain = domain_override
            t = loader.get_template(email_template_name)
            c = {
                'email': user.email,
                'domain': domain,
                'site_name': site_name,
                'uid': int_to_base36(user.id),
                'user': user,
                'token': token_generator.make_token(user),
                'protocol': use_https and 'https' or 'http',
            }
            send_mail(tr("Password reset on %s") % site_name,
                t.render(Context(c)), from_email, [user.email])

#------------------------------------------------------------------------------
class PasswordSetForm(forms.Form):
    """
    A form that lets a user change set his/her password without
    entering the old password
    """
    new_password1 = PasswordField(label=tr("New password"))
    new_password2 = PasswordField(label=tr("New Password (confirmation)"),
                                help_text=tr("Enter the same password as above, for verification."))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(PasswordSetForm, self).__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError(tr("The two password fields didn't match."))
        return password2

    def save(self, commit=True):
        self.user.set_password(self.cleaned_data['new_password1'])
        if commit:
            self.user.save()
        return self.user

#------------------------------------------------------------------------------
class PasswordChangeForm(PasswordSetForm):
    """
    A form that lets a user change his/her password by entering
    their old password.
    """
    old_password = PasswordField(label=tr("Old Password"))

    def clean_old_password(self):
        """
        Validates that the old_password field is correct.
        """
        old_password = self.cleaned_data["old_password"]
        if not self.user.check_password(old_password):
            raise forms.ValidationError(tr("Your old password was entered incorrectly. Please enter it again."))
        return old_password
PasswordChangeForm.base_fields.keyOrder = ['old_password', 'new_password1', 'new_password2']


#------------------------------------------------------------------------------
class AddApiKeyForm(forms.Form):
    keyID = forms.IntegerField(label=tr("API Key ID"))
    vCode = forms.CharField(label=tr("Verification Code"),
                            widget=forms.TextInput(attrs={'size':'100'}))
    user = AnonymousUser()

    def clean_keyID(self):
        """
        Validate that the supplied keyID is not already associated to another User.
        """
        if UserAPIKey.objects.filter(keyID=self.cleaned_data['keyID']):
            raise forms.ValidationError(tr("This API Key is already registered."))
        return self.cleaned_data['keyID']

    def clean(self):
        cleaned_data = self.cleaned_data

        keyID = cleaned_data.get("keyID")
        vCode = cleaned_data.get("vCode")

        if keyID is not None and vCode is not None:
            # test if API credentials are valid and if EVE account contains
            # characters which are members of the corporation
            try:
                self.characters = api.get_account_characters(UserAPIKey(keyID=keyID, vCode=vCode))
                valid_account = False
                for c in self.characters:
                    exists = Member.objects.filter(characterID=c.characterID).exists()
                    valid_account |= exists and c.is_corped
                if valid_account:
                    ids = [ c.characterID for c in self.characters ]
                    if Member.objects.filter(characterID__in=ids).exclude(owner=None).exclude(owner=self.user):
                        self._errors["keyID"] = self.error_class([tr("A character from this account is already registered by another player")])
                        del cleaned_data["keyID"]
                else:
                    self._errors["keyID"] = self.error_class([tr("This EVE account has no character member of the corporation")])
                    del cleaned_data["keyID"]
            except eveapi.Error as e:
                self._errors["keyID"] = self.error_class([str(e)])
                self._errors["vCode"] = self.error_class([str(e)])
                del cleaned_data["keyID"]
                del cleaned_data["vCode"]

        return cleaned_data

#------------------------------------------------------------------------------
class EditApiKeyForm(forms.Form):
    keyID = forms.IntegerField(label=tr("API Key ID"), widget=forms.TextInput(attrs={'readonly':'readonly'}))
    vCode = forms.CharField(label=tr("Verification Code"),
                            widget=forms.TextInput(attrs={'size':'100'}))
    user = AnonymousUser()

    def clean(self):
        cleaned_data = self.cleaned_data

        keyID = cleaned_data.get("keyID")
        vCode = cleaned_data.get("vCode")

        if keyID is not None and vCode is not None:
            # test if API credentials are valid and if EVE account contains
            # characters which are members of the corporation
            try:
                self.characters = api.get_account_characters(UserAPIKey(keyID=keyID, vCode=vCode))
                valid_account = False
                for c in self.characters:
                    exists = Member.objects.filter(characterID=c.characterID).exists()
                    valid_account |= exists and c.is_corped
                if valid_account:
                    ids = [ c.characterID for c in self.characters ]
                    if Member.objects.filter(characterID__in=ids).exclude(owner__in=[None, self.user]):
                        self._errors["keyID"] = self.error_class([tr("A character from this account is already registered by another player")])
                        del cleaned_data["keyID"]
                else:
                    self._errors["keyID"] = self.error_class([tr("This EVE account has no character member of the corporation")])
                    del cleaned_data["keyID"]
            except eveapi.Error as e:
                self._errors["vCode"] = self.error_class([str(e)])
                del cleaned_data["vCode"]

        return cleaned_data

#------------------------------------------------------------------------------
class AddBindingForm(forms.Form):
    username = forms.CharField(label=tr("External Username"))
    password = forms.CharField(label=tr("External Password"), widget=forms.PasswordInput)

    def __init__(self, data=None, app=None, user=None):
        forms.Form.__init__(self, data=data)
        self.app = app
        self.user = user

    def clean(self):
        cleaned_data = self.cleaned_data
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")

        data = {
            'username' : username,
            'password' : password
        }
        try:
            request = urllib2.Request(self.app.url, urllib.urlencode(data))
            response = urllib2.urlopen(request)
            content = response.read().strip()
            if content:
                self.external_id = int(content)
                query = UserBinding.objects.exclude(user=self.user).filter(external_app=self.app)
                if query.filter(external_id=self.external_id):
                    raise forms.ValidationError("This external user is already bound to someone else.")
            else:
                # content is empty
                raise forms.ValidationError("Authentication failed. Bad username or password.")
        except ValueError:
            # bad response from server
            raise forms.ValidationError("Bad response from external application.")

        return cleaned_data
