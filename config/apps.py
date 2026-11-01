from django.contrib.admin.apps import AdminConfig


class ContestAdminConfig(AdminConfig):
    default_site = "config.admin.ContestAdminSite"
