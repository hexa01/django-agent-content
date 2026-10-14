from django.urls import path

from . import views

app_name = 'agent_content'

urlpatterns = [
    path('', views.index, name='index'),
    path('<slug:name>/', views.collection, name='collection'),
    path('<slug:name>/<str:lookup>/', views.item, name='item'),
    path('<slug:name>/<str:lookup>/<slug:sub>/', views.member, name='member'),
]
