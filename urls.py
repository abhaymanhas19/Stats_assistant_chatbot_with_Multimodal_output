from django.urls import path

from . import views

urlpatterns = [
    path("projects/", views.ProjectListView.as_view(), name="stats-projects"),
    path("projects/<int:project_id>/", views.ProjectDetailView.as_view(), name="stats-project-detail"),
    path("projects/<int:project_id>/state/", views.ProjectStateView.as_view(), name="stats-project-state"),
    path("projects/<int:project_id>/files/", views.ProjectFilesView.as_view(), name="stats-project-files"),
    path("projects/<int:project_id>/files/<int:row_id>/", views.ProjectFileDetailView.as_view(), name="stats-project-file"),
    path(
        "projects/<int:project_id>/files/<int:row_id>/content/",
        views.ProjectFileContentView.as_view(),
        name="stats-project-file-content",
    ),
    path("projects/<int:project_id>/threads/", views.ThreadListView.as_view(), name="stats-threads"),
    path("projects/<int:project_id>/threads/<uuid:thread_id>/", views.ThreadDetailView.as_view(), name="stats-thread-detail"),
    path(
        "projects/<int:project_id>/threads/<uuid:thread_id>/messages/",
        views.ThreadMessagesView.as_view(),
        name="stats-thread-messages",
    ),
    path("projects/<int:project_id>/chat/", views.ChatView.as_view(), name="stats-chat"),
    path("projects/<int:project_id>/engine/session/", views.engine_session, name="stats-engine-session"),
    path("projects/<int:project_id>/engine/files/<int:row_id>/", views.engine_file, name="stats-engine-file"),
    path("projects/<int:project_id>/engine/call/", views.engine_call, name="stats-engine-call"),
    path("projects/<int:project_id>/engine/run-code/", views.engine_run_code, name="stats-engine-run-code"),
    path("projects/<int:project_id>/engine/run-step/", views.engine_run_step, name="stats-engine-run-step"),
    path("projects/<int:project_id>/engine/snapshot/", views.engine_snapshot, name="stats-engine-snapshot"),
    path("projects/<int:project_id>/engine/restore/", views.engine_restore, name="stats-engine-restore"),
]
