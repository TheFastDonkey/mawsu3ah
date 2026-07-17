"""Project-level forms."""

from django import forms
from django.core.validators import EmailValidator


class ContactForm(forms.Form):
    name = forms.CharField(
        label="الاسم",
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "c-input", "placeholder": "اسمك الكامل"}
        ),
    )
    email = forms.EmailField(
        label="البريد الإلكتروني",
        validators=[EmailValidator(message="أدخل عنوان بريد إلكتروني صالح.")],
        widget=forms.EmailInput(
            attrs={"class": "c-input", "placeholder": "email@example.com"}
        ),
    )
    subject = forms.CharField(
        label="الموضوع",
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": "c-input", "placeholder": "موضوع الرسالة"}
        ),
    )
    message = forms.CharField(
        label="الرسالة",
        min_length=10,
        error_messages={
            "required": "الرسالة لا يمكن أن تكون فارغة.",
            "min_length": "الرسالة قصيرة جداً؛ يُرجى كتابة تفاصيل أكثر.",
        },
        widget=forms.Textarea(
            attrs={
                "class": "c-textarea",
                "placeholder": "اكتب رسالتك هنا...",
                "rows": 6,
            }
        ),
    )

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if not message:
            raise forms.ValidationError("الرسالة لا يمكن أن تكون فارغة.")
        return message
