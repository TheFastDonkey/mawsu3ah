from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class User(AbstractUser):
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    is_expert = models.BooleanField(default=False)
    reputation = models.IntegerField(default=0)
    expert_flair = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="شارة الخبير",
        help_text="النص الذي يظهر بجانب اسم المستخدم الخبير. إذا ترك فارغاً، ستظهر 'خبير'.",
    )
    flairs = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated list of user flairs.",
    )
    magic_link_nonce = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Single-use nonce for magic-link login.",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.username

    def get_short_name(self):
        return self.username

    def get_full_name(self):
        return self.username

    @property
    def flair_list(self):
        return [f.strip() for f in self.flairs.split(",") if f.strip()]

    @property
    def expert_label(self):
        if not self.is_expert:
            return ""
        return self.expert_flair.strip() or "خبير"


class Profile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="المستخدم",
    )
    avatar = models.ImageField(
        upload_to="avatars/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="الصورة الشخصية",
        help_text="اختيارية. JPEG أو PNG أو WebP، بحد أقصى 2 ميجابايت.",
    )
    bio = models.TextField(
        max_length=500,
        blank=True,
        verbose_name="نبذة",
    )
    location = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="الموقع",
    )
    website = models.URLField(
        blank=True,
        verbose_name="الموقع الإلكتروني",
    )
    twitter_x = models.URLField(
        blank=True,
        verbose_name="رابط X / Twitter",
    )
    telegram = models.URLField(
        blank=True,
        verbose_name="رابط Telegram",
    )
    facebook = models.URLField(
        blank=True,
        verbose_name="رابط Facebook",
    )
    class Meta:
        verbose_name = "ملف شخصي"
        verbose_name_plural = "ملفات شخصية"

    def __str__(self):
        return f"ملف {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
