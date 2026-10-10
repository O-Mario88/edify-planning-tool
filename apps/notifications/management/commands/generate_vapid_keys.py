"""Make the key pair a deployment signs its phone notifications with."""

from django.core.management.base import BaseCommand

from apps.notifications import webpush


class Command(BaseCommand):
    help = (
        "Print a new Web Push (VAPID) key pair as environment lines. Set them "
        "once per environment and keep them: a browser subscribes with the "
        "public key, so a new pair orphans every device already subscribed."
    )

    def handle(self, *args, **options):
        public, private = webpush.generate_vapid_keys()
        self.stdout.write(f"WEBPUSH_VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"WEBPUSH_VAPID_PRIVATE_KEY={private}")
