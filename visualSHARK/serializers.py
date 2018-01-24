#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json

from rest_framework_mongoengine import serializers
from rest_framework_mongoengine.fields import ObjectIdField
from rest_framework import serializers as rserializers
# from rest_framework import fields as rfields

from .models import Commit, Project, VCSSystem, IssueSystem, FileAction, Tag, CodeEntityState, Issue, Message, People, MailingList, File, MynbouData
from .models import CommitGraph, CommitLabelField, VSJob, VSJobType


class CommitLabelFieldSerializer(rserializers.ModelSerializer):

    class Meta:
        model = CommitLabelField
        fields = ('id', 'approach', 'name', 'description', 'label')


class CommitGraphSerializer(rserializers.ModelSerializer):

    class Meta:
        model = CommitGraph
        fields = ('id', 'vcs_system_id', 'title', 'directed_graph')
        lookup_field = ('vcs_system_id')

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret['directed_graph'] = json.load(instance.directed_graph.file)
        return ret


class FileSerializer(serializers.DocumentSerializer):

    class Meta:
        model = File
        fields = ('id', 'vcs_system_id', 'path')


class PersonSerializer(serializers.DocumentSerializer):

    class Meta:
        model = People
        fields = ('id', 'email', 'name', 'username')


class CommitSerializer(serializers.DocumentSerializer):
    class Meta:
        model = Commit
        fields = ('vcs_system_id', 'revision_hash', 'committer_date')


class TagSerializer(serializers.DocumentSerializer):
    commit = CommitSerializer()

    class Meta:
        model = Tag
        fields = ('vcs_system_id', 'name', 'commit_id', 'message', 'tagger_id', 'date', 'date_offset', 'commit')


class TagListSerializer(rserializers.Serializer):
    name = rserializers.CharField(read_only=True)
    message = rserializers.CharField(read_only=True)


class IssueListSerializer(rserializers.Serializer):
    id = rserializers.CharField(read_only=True)
    name = rserializers.CharField(read_only=True)


class LabelListSerializer(rserializers.Serializer):
    name = rserializers.CharField(read_only=True)
    value = rserializers.BooleanField(read_only=True)


class SingleCommitSerializer(serializers.DocumentSerializer):
    author = PersonSerializer()
    committer = PersonSerializer()
    commit_id = ObjectIdField(source='_id')
    tags = TagListSerializer(many=True)
    issue_links = IssueListSerializer(many=True)
    labels = LabelListSerializer(many=True)

    class Meta:
        model = Commit
        fields = ('commit_id', 'parents', 'revision_hash', 'vcs_system_id', 'revision_hash', 'committer_date', 'author_date', 'message', 'branches', 'author_id', 'committer_id', 'author', 'committer', 'committer_date_offset', 'author_date_offset', 'tags', 'issue_links', 'labels')


class RecSingleMessageSerializer(serializers.DocumentSerializer):

    class Meta:
        model = Message
        fields = ('id', 'subject', 'date')


class SingleMessageSerializer(serializers.DocumentSerializer):
    sender = PersonSerializer()
    recipients = PersonSerializer(many=True)
    cc_ids = PersonSerializer(many=True)
    reference_ids = RecSingleMessageSerializer(many=True)
    in_reply_to_id = RecSingleMessageSerializer()

    class Meta:
        model = Message
        fields = ('subject', 'body', 'date', 'sender', 'recipients', 'mailing_list_id', 'reference_ids', 'in_reply_to_id', 'cc_ids', 'patches')


class SingleIssueSerializer(serializers.DocumentSerializer):
    creator = PersonSerializer()
    reporter = PersonSerializer()
    assignee = PersonSerializer()

    class Meta:
        model = Issue
        fields = ('external_id', 'creator', 'reporter', 'assignee', 'title', 'desc', 'issue_type', 'priority', 'status', 'affects_versions', 'components', 'labels', 'resolution', 'fix_versions')


class FileRSerializer(rserializers.Serializer):
    path = rserializers.CharField(read_only=True)


class FileActionSerializer(serializers.DocumentSerializer):
    file = FileRSerializer()
    old_file = FileRSerializer()

    class Meta:
        model = FileAction
        fields = ('commit_id', 'file_id', 'old_file_id', 'mode', 'size_at_commit', 'lines_added', 'lines_deleted', 'is_binary', 'file', 'old_file')


class CodeEntityStateSerializer(serializers.DocumentSerializer):

    class Meta:
        model = CodeEntityState
        fields = ('long_name', 'commit_id', 'file_id', 'ce_type', 'imports', 'metrics')


class ProjectSerializer(serializers.DocumentSerializer):
    class Meta:
        model = Project
        fields = ('id', 'name')


class VcsSerializer(serializers.DocumentSerializer):
    class Meta:
        model = VCSSystem
        fields = ('id', 'project_id', 'last_updated', 'repository_type', 'url')


class IssueSystemSerializer(serializers.DocumentSerializer):
    class Meta:
        model = IssueSystem
        fields = ('id', 'project_id', 'url', 'last_updated')


class MailingListSerializer(serializers.DocumentSerializer):
    class Meta:
        model = MailingList
        fields = ('id', 'project_id', 'name', 'last_updated')


class IssueSerializer(serializers.DocumentSerializer):
    class Meta:
        model = Issue
        fields = ('id', 'external_id', 'issue_system_id', 'title', 'desc', 'created_at', 'updated_at', 'status')


class MessageSerializer(serializers.DocumentSerializer):
    class Meta:
        model = Message
        fields = ('id', 'mailing_list_id', 'subject', 'body', 'date')


class PeopleSerializer(serializers.DocumentSerializer):
    class Meta:
        model = People
        fields = ('id', 'email', 'name', 'username')


class AuthSerializer(rserializers.Serializer):
    key = rserializers.CharField(read_only=True)
    user = rserializers.CharField(read_only=True)


class ProductSerializer(serializers.DocumentSerializer):

    class Meta:
        model = MynbouData
        fields = ('id', 'vcs_system_id', 'name', 'file', 'path_approach', 'bugfix_label', 'metric_approach', 'last_updated')


class VSJobTypeSerializer(rserializers.ModelSerializer):

    class Meta:
        model = VSJobType
        fields = ('ident', 'name')


class VSJobSerializer(rserializers.ModelSerializer):
    requested_by = rserializers.HiddenField(
        default=rserializers.CurrentUserDefault()
    )
    # job_type = rserializers.PrimaryKeyRelatedField(queryset=VSJobType.objects.all())
    job_type = VSJobTypeSerializer(read_only=True)

    class Meta:
        model = VSJob
        fields = ('id', 'job_type', 'requested_by', 'created_at', 'executed_at', 'error_count', 'data', 'result')
