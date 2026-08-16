app_name = "omnieast"
app_title = "Omnieast"
app_publisher = "Shahzad Naser"
app_description = "Support customization for ERPNext"
app_email = "shahzadnaser1122@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "omnieast",
# 		"logo": "/assets/omnieast/logo.png",
# 		"title": "Omnieast",
# 		"route": "/omnieast",
# 		"has_permission": "omnieast.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/omnieast/css/omnieast.css"
# app_include_js = "/assets/omnieast/js/omnieast.js"

# include js, css files in header of web template
# web_include_css = "/assets/omnieast/css/omnieast.css"
# web_include_js = "/assets/omnieast/js/omnieast.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "omnieast/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "omnieast/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "omnieast.utils.jinja_methods",
# 	"filters": "omnieast.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "omnieast.install.before_install"
# after_install = "omnieast.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "omnieast.uninstall.before_uninstall"
# after_uninstall = "omnieast.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "omnieast.utils.before_app_install"
# after_app_install = "omnieast.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "omnieast.utils.before_app_uninstall"
# after_app_uninstall = "omnieast.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "omnieast.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Leave Application": {
        "on_submit": "omnieast.omnieast.doctype.business_travel_request.business_travel_request.create_travel_request"
    },
    "Journal Entry": {
        "on_submit": "omnieast.overrides.journal_entry.on_submit",
        "on_cancel": "omnieast.overrides.journal_entry.on_cancel",
    },
	# "*": {
	# 	"on_update": "method",
	# 	"on_cancel": "method",
	# 	"on_trash": "method"
	# }
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily_long": [
        "omnieast.scheduled_tasks.update_narration_in_gle.update_narration_in_gl_entry"
    ],
    "cron": {
        "*/10 * * * *": [
            "omnieast.api.attendance.sync_att_time"
        ]
    }
	# "all": [
	# 	"omnieast.tasks.all"
	# ],
	# "daily": [
	# 	"omnieast.tasks.daily"
	# ],
	# "hourly": [
	# 	"omnieast.tasks.hourly"
	# ],
	# "weekly": [
	# 	"omnieast.tasks.weekly"
	# ],
	# "monthly": [
	# 	"omnieast.tasks.monthly"
	# ],
}

fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [["name", "in", ["Project-total_indirect_cost"]]],
    },
]

# Testing
# -------

# before_tests = "omnieast.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
extend_doctype_class = {
	"Job Requisition": "omnieast.overrides.job_requisition.CustomJobRequisitionMixin",
    "Workspace Sidebar": "omnieast.overrides.workspace_sidebar.CustomWorkspaceSidebar",
    "Project": "omnieast.overrides.project.CustomProjectMixin",
}

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"hrms.hr.doctype.leave_application.leave_application.get_leave_details": "omnieast.overrided_whitelisted.leave_application.get_leave_details"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "omnieast.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["omnieast.utils.before_request"]
# after_request = ["omnieast.utils.after_request"]

# Job Events
# ----------
# before_job = ["omnieast.utils.before_job"]
# after_job = ["omnieast.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"omnieast.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

