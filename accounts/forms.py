import contextlib

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import FileExtensionValidator

from .image_utils import process_avatar_image, validate_avatar_image
from .models import Profile

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        return email.strip().lower()

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        return username.strip()


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email"]

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        return email.strip().lower()

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        return username.strip()


class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            "avatar",
            "bio",
            "location",
            "website",
            "twitter_x",
            "telegram",
            "facebook",
        ]
        help_texts = {
            "avatar": "اختيارية. JPEG أو PNG أو WebP، بحد أقصى 2 ميجابايت.",
        }
        widgets = {
            "bio": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "نبذة قصيرة عنك…",
                    "class": "c-textarea",
                }
            ),
            "location": forms.TextInput(
                attrs={"placeholder": "مثال: الرياض، المملكة العربية السعودية", "class": "c-input"}
            ),
            "website": forms.URLInput(attrs={"placeholder": "https://…", "class": "c-input"}),
            "twitter_x": forms.URLInput(attrs={"placeholder": "https://x.com/…", "class": "c-input"}),
            "telegram": forms.URLInput(attrs={"placeholder": "https://t.me/…", "class": "c-input"}),
            "facebook": forms.URLInput(attrs={"placeholder": "https://facebook.com/…", "class": "c-input"}),
        }
        labels = {
            "avatar": "الصورة الشخصية",
            "bio": "نبذة",
            "location": "الموقع",
            "website": "الموقع الإلكتروني",
            "twitter_x": "X / Twitter",
            "telegram": "Telegram",
            "facebook": "Facebook",
        }
        # Apply server-side extension whitelist in addition to Pillow
        # validation. This rejects obviously bad file extensions early.
        field = Profile._meta.get_field("avatar")
        field.validators.append(FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"]))

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar:
            validate_avatar_image(avatar)
        return avatar

    def save(self, commit=True):
        old_avatar = None
        if self.instance.pk:
            with contextlib.suppress(Profile.DoesNotExist):
                old_avatar = Profile.objects.get(pk=self.instance.pk).avatar

        profile = super().save(commit=False)
        avatar = self.cleaned_data.get("avatar")

        if avatar:
            if old_avatar and old_avatar != avatar:
                old_avatar.delete(save=False)
            profile.avatar = process_avatar_image(avatar)

        if commit:
            profile.save()
        return profile
