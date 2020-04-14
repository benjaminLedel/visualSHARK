#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import io
import logging
import tempfile
import git
import shutil
import magic
import random

from datetime import datetime, date
from dateutil.relativedelta import relativedelta

import networkx as nx

from django.contrib.auth import authenticate
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.models import Permission


from rest_framework.views import APIView
from rest_framework import exceptions
from rest_framework import viewsets as rviewsets
from rest_framework.response import Response
from rest_framework_mongoengine import viewsets
from rest_framework.decorators import detail_route, list_route
from rest_framework import filters
from rest_framework import status
import django_filters

from mongoengine.queryset.visitor import Q
from bson.objectid import ObjectId

from .models import Commit, Project, VCSSystem, IssueSystem, Token, People, FileAction, File, Tag, CodeEntityState, \
    Issue, Message, MailingList, MynbouData, TravisBuild, Branch, Event, Hunk, ProjectAttributes
from .models import CommitGraph, CommitLabelField, ProjectStats, VSJob, VSJobType, IssueValidation, IssueValidationUser, UserProfile
from .models import LeaderboardSnapshot

from .serializers import CommitSerializer, ProjectSerializer, VcsSerializer, IssueSystemSerializer, AuthSerializer, SingleCommitSerializer, FileActionSerializer, TagSerializer, CodeEntityStateSerializer, IssueSerializer, PeopleSerializer, MessageSerializer, SingleIssueSerializer, MailingListSerializer, FileSerializer, BranchSerializer, HunkSerializer
from .serializers import CommitGraphSerializer, CommitLabelFieldSerializer, ProductSerializer, SingleMessageSerializer, VSJobSerializer, IssueLabelSerializer, IssueLabelConflictSerializer

from django.core.exceptions import FieldDoesNotExist
from django.db.models.fields.reverse_related import ForeignObjectRel, OneToOneRel

from rest_framework.filters import OrderingFilter

from .util import prediction
from .util.helper import tag_filter, OntdekBaan
from .util.helper import Label, TICKET_TYPE_MAPPING
from .util.helper import get_file_lines, get_change_view

# from visibleSHARK.util.label import LabelPath
# from mynbou.label import LabelPath

log = logging.getLogger()


class RelatedOrderingFilter(OrderingFilter):
    """Extends OrderingFilter to support ordering by fields in related models."""

    def is_valid_field(self, model, field):
        """
        Return true if the field exists within the model (or in the related

        model specified using the Django ORM __ notation)
        """
        components = field.split('__', 1)
        try:

            field = model._meta.get_field(components[0])

            if isinstance(field, OneToOneRel):
                return self.is_valid_field(field.related_model, components[1])

            # reverse relation
            if isinstance(field, ForeignObjectRel):
                return self.is_valid_field(field.model, components[1])

            # foreign key
            if field.rel and len(components) == 2:
                return self.is_valid_field(field.rel.to, components[1])
            return True
        except FieldDoesNotExist:
            return False

    def remove_invalid_fields(self, queryset, fields, view):
        return [term for term in fields if self.is_valid_field(queryset.model, term.lstrip('-'))]


class Auth(APIView):
    permission_classes = ()
    schema = None

    def get(self, request):
        username = request.META.get('HTTP_X_USER')
        password = request.META.get('HTTP_X_PASS')

        if not username or not password:
            raise exceptions.AuthenticationFailed()

        user = authenticate(username=username, password=password)
        if user is None:
            raise exceptions.AuthenticationFailed()

        # we just try to avoid ReconnectErrors here
        try:
            _ = Project.objects.count()
        except:
            pass

        token = Token.objects.filter(user=user)
        ass = AuthSerializer(token, many=True)
        perms = user.get_group_permissions().union(user.get_all_permissions())  # union of group and user perms, as strings

        tmp = ass.data
        tmp[0]['is_superuser'] = user.is_superuser
        tmp[0]['channel'] = user.profile.channel
        tmp[0]['permissions'] = [p.split('.')[-1] for p in perms]  # remove applabel, i.e., visualSHARK.edit_issue_labels -> edit_issue_labels

        return Response(tmp)


class MongoReadOnlyModelViewSet(viewsets.ReadOnlyModelViewSet):
    """Helper to allow filtering and searching via the ReST API."""

    mongo_search_fields = ()

    def get_queryset(self):
        """Apply requested searches and filters to the queryset."""
        qry = super().get_queryset()

        # detect filtering
        ft = {}
        for ff in self.filter_fields:
            fr = self.request.query_params.get(ff, None)
            if not fr:
                continue
            # date is passed as a string we need to manually reset it here
            if 'date' in ff:
                ft[ff] = datetime.strptime(fr, '%Y-%m-%dT%H:%M:%S')
            else:
                ft[ff] = fr
        qry = qry.filter(**ft)

        # detect searching
        search = self.request.query_params.get('search', None)
        if search:
            q_objects = Q()
            for sf in self.mongo_search_fields:
                # q_objects.add(Q(sf__icontains=search), Q.OR)
                q_objects |= Q(**{'{}__icontains'.format(sf): search})
            qry = qry.filter(q_objects)
        return qry


class TagViewSet(MongoReadOnlyModelViewSet):
    """API Endpoint for Tags."""
    read_perm = 'view_commits'
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    ordering_fields = ('name', 'date')
    filter_fields = ('vcs_system_id', 'name')
    mongo_search_fields = ('name',)

    def _inject_data(self, qry):
        ret = []
        for d in qry:
            dat = d.to_mongo()
            dat['commit'] = Commit.objects.get(id=d.commit_id)
            ret.append(dat)
        return ret

    def list(self, request):
        """Nested serializer, we need additional actions for pagination."""
        qry = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qry)
        if page is not None:
            serializer = self.serializer_class(self._inject_data(page), many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.serializer_class(self._inject_data(qry), many=True)
        return Response(serializer.data)


class CommitViewSet(MongoReadOnlyModelViewSet):
    """API Endpoint for Commits."""
    read_perm = 'view_commits'
    queryset = Commit.objects.only('id', 'revision_hash', 'vcs_system_id', 'committer_date', 'committer_date_offset', 'author_date', 'author_date_offset', 'message', 'committer_id', 'author_id', 'labels', 'linked_issue_ids', 'branches', 'parents')
    serializer_class = CommitSerializer
    filter_fields = ('revision_hash', 'vcs_system_id', 'committer_date__gte', 'committer_date__lt')
    ordering_fields = ('id', 'revision_hash', 'committer_date')
    mongo_search_fields = ('revision_hash', 'committer_date', 'message')

    def get_queryset(self):
        """Add special case if we search for a person, could be committer or author."""
        qry = super().get_queryset()
        person_id = self.request.query_params.get('person_id', None)
        if person_id:
            qry = qry.filter(Q(author_id=person_id) or Q(committer_id=person_id))
        return qry

    def retrieve(self, request, id=None):
        """Add additional information the each commit."""
        vcs_system_id = self.request.query_params.get('vcs_system_id', None)
        if vcs_system_id:
            commit = Commit.objects.get(vcs_system_id=vcs_system_id, revision_hash=id)
        else:
            commit = Commit.objects.get(revision_hash=id)

        tags = []
        for t in Tag.objects.filter(commit_id=commit.id):
            tags.append({'name': t.name, 'message': t.message})

        issue_links = []
        for li in commit.linked_issue_ids:
            i = Issue.objects.get(id=li)
            issue_links.append({'name': i.external_id, 'id': i.id})

        validated_issue_links = []
        for li in commit.fixed_issue_ids:
            i = Issue.objects.get(id=li)
            validated_issue_links.append({'name': i.external_id, 'id': i.id})

        labels = []
        for l, v in commit.labels.items():
            labels.append({'name': l, 'value': v})

        dat = commit.to_mongo()
        dat['author'] = People.objects.get(id=commit.author_id)
        dat['committer'] = People.objects.get(id=commit.committer_id)
        dat['tags'] = tags
        dat['issue_links'] = issue_links
        dat['validated_issue_links'] = validated_issue_links
        dat['labels'] = labels
        serializer = SingleCommitSerializer(dat)
        return Response(serializer.data)


class FileActionViewSet(MongoReadOnlyModelViewSet):
    """API Endpoint for FileActions."""
    read_perm = 'view_commits'
    queryset = FileAction.objects.all()
    serializer_class = FileActionSerializer
    ordering_fields = ('mode', 'lines_added', 'lines_deleted', 'size_at_commit')
    filter_fields = ('commit_id',)

    def get_queryset(self):
        qry = super().get_queryset()

        search = self.request.query_params.get('search', None)

        # This is as efficient as it is going to get with mongodb, we can at least restrict files to the vcs system but
        # the list can still get very large
        if search:
            c = self.request.query_params.get('commit_id', None)
            if c:
                commit = Commit.objects.get(id=c)
                q_objects = Q(file_id__in=File.objects.filter(vcs_system_id=commit.vcs_system_id, path__icontains=search).values_list('id'))
            else:
                q_objects = Q(file_id__in=File.objects.filter(path__icontains=search).values_list('id'))
            qry = qry.filter(q_objects)
        return qry

    def _inject_data(self, qry):
        ret = []
        for d in qry:
            dat = d.to_mongo()
            dat['commit_id'] = d.commit_id
            dat['id'] = d.id
            dat['file'] = File.objects.get(id=d.file_id)
            if d.old_file_id:
                dat['old_file'] = File.objects.get(id=d.old_file_id)
            else:
                dat['old_file'] = None

            dat['induced_by'] = []
            for inducing_fa in FileAction.objects.filter(induces__match={'change_file_action_id': d.id}):
                for ind in inducing_fa.induces:

                    if ind['change_file_action_id'] == d.id:
                        blame_commit = Commit.objects.get(id=inducing_fa.commit_id)

                        if blame_commit.revision_hash not in dat['induced_by']:
                            dat['induced_by'].append(blame_commit.revision_hash)
            ret.append(dat)
        return ret

    def list(self, request):
        """Again a nested serializer."""
        qry = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qry)
        if page is not None:
            serializer = self.serializer_class(self._inject_data(page), many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.serializer_class(self._inject_data(qry), many=True)
        return Response(serializer.data)


class CodeEntityStateViewSet(MongoReadOnlyModelViewSet):
    """API Endpoint for CodeEntityStates."""
    read_perm = 'view_commits'
    queryset = CodeEntityState.objects.all()
    serializer_class = CodeEntityStateSerializer
    ordering_fields = ('ce_type', 'long_name')
    filter_fields = ('commit_id', 'ce_type', 'long_name')
    mongo_search_fields = ('long_name',)

    # def _inject_data(self, qry):
    #     ret = []
    #     for d in qry:
    #         dat = d.to_mongo()
    #         ret.append(dat)
    #     return ret

    # def list(self, request):
    #     """Again a nested serializer."""
    #     qry = self.filter_queryset(self.get_queryset())
    #     page = self.paginate_queryset(qry)
    #     if page is not None:
    #         serializer = self.serializer_class(self._inject_data(page), many=True)
    #         return self.get_paginated_response(serializer.data)
    #     serializer = self.serializer_class(self._inject_data(qry), many=True)
    #     return Response(serializer.data)


class HunkViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_commits'
    queryset = Hunk.objects.all()
    serializer_class = HunkSerializer
    filter_fields = ('file_action_id', 'id')
    mongo_search_fields = ('content',)


class FileViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_files'
    queryset = File.objects.all()
    serializer_class = FileSerializer
    ordering_fields = ('path',)
    filter_fields = ('vcs_system_id', 'path', 'id')
    mongo_search_fields = ('path',)


class ProjectViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_projects'
    queryset = Project.objects.all().order_by('name')
    serializer_class = ProjectSerializer

    def list(self, request):
        projects = []
        query = ProjectAttributes.objects.filter(is_visible=True)

        if request.user.is_superuser:
            query = ProjectAttributes.objects.all()

        for pro in query.order_by('project_name'):
            projects.append(Project.objects.get(name=pro.project_name))

        serializer = self.serializer_class(projects, many=True)
        response = {}
        response["results"] = serializer.data
        return Response(response)


class VcsViewSet(viewsets.ReadOnlyModelViewSet):
    read_perm = 'view_commits'
    queryset = VCSSystem.objects.all()
    serializer_class = VcsSerializer
    filter_fields = ('project_id')


class IssueSystemViewSet(viewsets.ReadOnlyModelViewSet):
    read_perm = 'view_issues'
    queryset = IssueSystem.objects.all()
    serializer_class = IssueSystemSerializer
    filter_fields = ('project_id')


class MailingListViewSet(viewsets.ReadOnlyModelViewSet):
    read_perm = 'view_messages'
    queryset = MailingList.objects.all()
    serializer_class = MailingListSerializer
    filter_fields = ('project_id')


class BranchViewSet(viewsets.ReadOnlyModelViewSet):
    read_perm = 'view_commits'
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    filter_fields = ('vcs_system_id')


class IssueViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_issues'
    queryset = Issue.objects.all()
    serializer_class = IssueSerializer
    ordering_fields = ('external_id', 'title', 'created_at', 'updated_at', 'status')
    filter_fields = ('issue_system_id', 'external_id', 'title', 'status')
    mongo_search_fields = ('title',)

    def get_queryset(self):
        """Handle special case for person search."""
        qry = super().get_queryset()
        person_id = self.request.query_params.get('person_id', None)
        if person_id:
            qry = qry.filter(Q(creator_id=person_id) | Q(assignee_id=person_id) | Q(reporter_id=person_id))
        return qry

    def retrieve(self, request, id=None):
        """Additional information for GET."""
        r = self.queryset.get(id=id)

        dat = r.to_mongo()
        dat['reporter'] = None
        dat['creator'] = None
        dat['assignee'] = None
        if r.reporter_id:
            dat['reporter'] = People.objects.get(id=r.reporter_id)
        if r.creator_id:
            dat['creator'] = People.objects.get(id=r.creator_id)
        if r.assignee_id:
            dat['assignee'] = People.objects.get(id=r.assignee_id)

        dat['events'] = []
        for e in Event.objects.filter(issue_id=r.id).order_by('created_at'):
            ev = {'created_at': e.created_at, 'author_id': e.author_id, 'status': e.status, 'old_value': e.old_value, 'new_value': e.new_value}
            ev['author'] = People.objects.get(id=e.author_id)
            dat['events'].append(ev)
        serializer = SingleIssueSerializer(dat)
        return Response(serializer.data)


class PeopleViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_people'

    queryset = People.objects.all()
    serializer_class = PeopleSerializer
    ordering_fields = ('name', 'username', 'email')
    filter_fields = ('name', 'username', 'email')
    mongo_search_fields = ('name', 'username', 'email')


class MessageViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_messages'

    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    filter_fields = ('mailing_list_id',)
    ordering_fields = ('subject', 'date')
    mongo_search_fields = ('subject',)

    def get_queryset(self):
        """Handle special case for person search."""
        qry = super().get_queryset()
        person_id = self.request.query_params.get('person_id', None)
        if person_id:
            qry = qry.filter(Q(from_id=person_id))
        return qry

    def retrieve(self, request, id=None):
        """Add additional information the each message."""
        obj = self.queryset.get(id=id)

        recipients = []
        for li in obj.to_ids:
            recipients.append(People.objects.get(id=li))

        cc_ids = []
        for li in obj.cc_ids:
            cc_ids.append(People.objects.get(id=li))

        patches = []
        for li in obj.patches:
            patches.append({'patch': li})

        reference_ids = []
        for li in obj.reference_ids:
            reference_ids.append(Message.objects.get(id=li))

        dat = obj.to_mongo()
        dat['sender'] = None
        dat['in_reply_to_id'] = None
        if obj.in_reply_to_id:
            dat['in_reply_to_id'] = Message.objects.get(id=obj.in_reply_to_id)
        if obj.from_id:
            dat['sender'] = People.objects.get(id=obj.from_id)
        dat['recipients'] = recipients
        dat['reference_ids'] = reference_ids
        dat['cc_ids'] = cc_ids
        dat['patches'] = patches
        serializer = SingleMessageSerializer(dat)
        return Response(serializer.data)


class CommitLabelFieldViewSet(rviewsets.ReadOnlyModelViewSet):
    read_perm = 'view_commits'

    queryset = CommitLabelField.objects.all()
    serializer_class = CommitLabelFieldSerializer


class CommitGraphViewSet(rviewsets.ReadOnlyModelViewSet):

    """Commit Graph ReST endpoint.

    This endpoint reads the commit graph nodes and their positions (according to graphviz) from the file
    generated during execution of the create_commit_graph command and returns it for the commit graph SVG.
    """

    read_perm = 'view_commits'
    queryset = CommitGraph.objects.all()
    serializer_class = CommitGraphSerializer
    lookup_field = ('vcs_system_id')
    filter_fields = ('vcs_system_id')

    @detail_route(methods=['get'])
    def mark_nodes(self, request, vcs_system_id=None):
        """Generic node marker.

        We can mark nodes according to search terms or because auf certain (boolan) labels.
        """
        search = request.query_params.get('searchMessage', None)
        label = request.query_params.get('label', None)
        travis = request.query_params.get('travis', None)

        response = {}

        if travis:
            travis_states = travis.split(',')
            for v in Commit.objects.filter(vcs_system_id=vcs_system_id).only(['revision_hash', 'id']):
                states = []
                for tj in TravisBuild.objects.filter(vcs_system_id=vcs_system_id, commit_id=v.id):
                    if tj.state.upper() not in travis_states:
                        continue
                    states.append('travis_{}'.format(tj.state))
                if states:
                    if v.revision_hash not in response.keys():
                        response[v.revision_hash] = []
                    response[v.revision_hash].append(list(set(states)))

        if label:
            for lid in label.split(','):
                labelfield = CommitLabelField.objects.get(pk=lid)
                label_name = '{}_{}'.format(labelfield.approach, labelfield.name)
                qry = {'vcs_system_id': vcs_system_id, 'labels__{}'.format(label_name): True}

                for c in Commit.objects.filter(**qry).only('revision_hash'):
                    if c.revision_hash in response.keys():
                        response[c.revision_hash].append(label_name)
                    else:
                        response[c.revision_hash] = [label_name]

        if search:
            for v in Commit.objects.filter(vcs_system_id=vcs_system_id, message__icontains=search).only('revision_hash'):
                if v.revision_hash in response.keys():
                    response[v.revision_hash].append('search')
                else:
                    response[v.revision_hash] = ['search']

            for v in Commit.objects.filter(vcs_system_id=vcs_system_id, revision_hash__icontains=search).only('revision_hash'):
                if v.revision_hash in response.keys():
                    response[v.revision_hash].append('search')
                else:
                    response[v.revision_hash] = ['search']

        return Response({'results': response})

    @detail_route(methods=['get'])
    def articulation_points(self, request, vcs_system_id=None):
        """Return list of nodes that are articulation points."""
        cg = CommitGraph.objects.get(vcs_system_id=vcs_system_id)
        dg = nx.read_gpickle(cg.directed_pickle.path)

        mark = nx.articulation_points(dg.to_undirected())

        return Response({'results': mark})

    @detail_route(methods=['get'])
    def product_path(self, request, vcs_system_id=None):
        """Return path for the approach used in this exact product."""
        cg = CommitGraph.objects.get(vcs_system_id=vcs_system_id)

        product_ids = request.query_params.get('product_ids', None)

        resp = {'paths': [], 'products': []}
        if not product_ids:
            return Response(resp)

        dg = nx.read_gpickle(cg.directed_pickle.path)

        for product_id in product_ids.split(','):
            p = MynbouData.objects.get(id=product_id)

            # extract approach, start and end commit
            tmp = json.loads(p.file.read())
            approach = tmp['label_path_approach']
            start_commit = tmp['start_commit']
            end_commit = tmp['end_commit']

            nodes = set()
            # import importlib
            # mod = importlib.import_module('mynbouSHARK.path_approaches.{}'.format(approach))
            if approach == 'commit_to_commit':
                c = OntdekBaan(dg)
                for path in c.get_all_paths(start_commit, end_commit):
                    nodes = nodes.union(set(path))

            resp['paths'].append(list(nodes))
            resp['products'].append(p.name)

        return Response(resp)

    @detail_route(methods=['get'])
    def ontdekbaan(self, request, vcs_system_id=None):
        cg = CommitGraph.objects.get(vcs_system_id=vcs_system_id)

        commit = request.query_params.get('commit', None)

        if not commit:
            raise Exception('need commits')

        dg = nx.read_gpickle(cg.directed_pickle.path)

        c = Commit.objects.get(revision_hash=commit)

        after1 = c.committer_date.date() + relativedelta(months=6)

        def break_condition1(commit):
            c = Commit.objects.get(revision_hash=commit)
            return c.committer_date.date() > after1

        o = OntdekBaan(dg)
        o.set_path(commit, 'backward')

        o2 = OntdekBaan(dg)
        o2.set_path(commit, 'forward', break_condition1)

        paths = []
        for path in o.all_paths():
            paths.append(path)

        for path in o2.all_paths():
            paths.append(path)

            # nodes = nodes.union(set(p))
        # path = nx.shortest_path(dg, start_commit, end_commit)
        # nodes = set(path)

        return Response({'paths': paths})


class ProductViewSet(MongoReadOnlyModelViewSet):
    read_perm = 'view_analytics'

    """Product data from mynbouSHARK."""
    queryset = MynbouData.objects.all()
    serializer_class = ProductSerializer
    filter_fields = ('vcs_system_id',)
    ordering_fields = ('name',)

    @detail_route(methods=['get'])
    def file(self, request, id=None):
        version = MynbouData.objects.get(id=id)
        return Response(json.loads(version.file.read()))

    @detail_route(methods=['get'])
    def file_download(self, request, id=None):
        version = MynbouData.objects.get(id=id)
        f = io.BytesIO(version.file.read())
        response = HttpResponse(f, content_type='application/json')
        response['Content-Disposition'] = 'attachment; filename="{}.json"'.format(version.name)
        return response


class PredictionEvaluationView(APIView):
    read_perm = 'view_analytics'

    def get(self, request):
        training = request.query_params.get('training', None)
        test = request.query_params.get('test', None)
        model = request.query_params.get('model', None)

        # 1. load files
        train = []
        te = []
        for train_id in training.split(','):
            train.append(json.loads(MynbouData.objects.get(id=train_id).file.read()))

        for test_id in test.split(','):
            te.append(json.loads(MynbouData.objects.get(id=test_id).file.read()))

        # 2. build model & evaluate
        pred = prediction.predict_evaluate(train, te, model)

        return Response(pred)


class PredictionView(APIView):
    read_perm = 'view_analytics'

    def get(self, request):
        training = request.query_params.get('training', None)
        test = request.query_params.get('test', None)
        model = request.query_params.get('model', None)

        # 1. load files
        train = []
        te = []
        for train_id in training.split(','):
            train.append(json.loads(MynbouData.objects.get(id=train_id).file.read()))

        for test_id in test.split(','):
            te.append(json.loads(MynbouData.objects.get(id=test_id).file.read()))

        # 2. build model & predict
        pred = prediction.predict(train, te, model)

        return Response(pred)


class StatsView(APIView):
    # TODO: update to serializer

    read_perm = 'view_stats'

    def get(self, request):
        projects = {'projects': {}}
        projects['num_projects'] = Project.objects.count()
        projects['num_commits'] = Commit.objects.count()
        projects['num_issues'] = Issue.objects.count()
        projects['num_emails'] = Message.objects.count()
        projects['num_files'] = File.objects.count()
        projects['num_people'] = People.objects.count()

        for pro in ProjectStats.objects.filter(stats_date=date.today()):
            projects['projects'][pro.project_name] = {
                'commits': pro.number_commits,
                'issues': pro.number_issues,
                'files': pro.number_files,
                'messages': pro.number_messages,
                'people': pro.number_people}
        return Response(projects)


class StatsHistoryView(APIView):
    # TODO: update to serializer

    read_perm = 'view_stats'

    def get(self, request):
        history = []
        for pro in ProjectStats.objects.values('stats_date').distinct().order_by('stats_date'):
            tmp = {'date': pro['stats_date'], 'commits': 0, 'issues': 0, 'files': 0, 'messages': 0, 'people': 0}
            for p in ProjectStats.objects.filter(stats_date=pro['stats_date']):
                tmp['commits'] += p.number_commits
                tmp['issues'] += p.number_issues
                tmp['files'] += p.number_files
                tmp['messages'] += p.number_messages
                tmp['people'] += p.number_people
            history.append(tmp)
        return Response(history)


class ReleaseView(APIView):

    read_perm = 'view_analytics'

    def get(self, request):
        vcs_system_id = request.GET.get('vcs_system_id', None)

        # its a get request
        discard_qualifiers = request.GET.get('discard_qualifiers', True) == 'true'
        discard_patch = request.GET.get('discard_patch', True) == 'true'
        discard_fliers = request.GET.get('discard_fliers', True) == 'true'

        vcs = VCSSystem.objects.get(id=vcs_system_id)
        project = Project.objects.get(id=vcs.project_id)

        versions = tag_filter(project.name, Tag.objects.filter(vcs_system_id=vcs_system_id), discard_qualifiers=discard_qualifiers, discard_patch=discard_patch, discard_fliers=discard_fliers)
        history = {'count': len(versions), 'results': versions}
        # print(history)
        return Response(history)

# todo: both classes can be refactored, affected entities could be part of CodeEntityStates, IssueLinkCandidates part of commit
class IssueLinkCandidatesView(APIView):
    """Get list of Candidates for issue linking for one commit id."""

    read_perm = 'view_analytics'

    def get(self, request):
        commit_id = request.GET.get('commit_id', None)
        commit = Commit.objects.get(id=commit_id)
        lbl = Label()
        ret = lbl.generate_candidates(commit)

        return Response(ret)


class AffectedEntitiesView(APIView):
    """Get list of Candidates for issue linking for one commit id."""

    read_perm = 'view_analytics'

    def get(self, request):
        commit_id = request.GET.get('commit_id', None)
        file_action_id = request.GET.get('file_action_id', None)

        commit = Commit.objects.get(id=commit_id)
        lbl = Label()
        ret = lbl.generate_affected_entities(commit, file_action_id)

        return Response(ret)


class VSJobViewSet(rviewsets.ModelViewSet):
    """Job information."""

    queryset = VSJob.objects.all()
    serializer_class = VSJobSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, filters.OrderingFilter)
    filter_fields = ('job_type__name',)
    ordering_fields = ('job_type', 'created_at', 'executed_at', 'error_count')
    search_fields = ('job_type__name',)

    def get_queryset(self):
        qry = super().get_queryset()
        return qry.filter(requested_by=self.request.user)

    @detail_route(methods=['post'])
    def requeue(self, request, pk=None):
        j = VSJob.objects.get(pk=pk)
        j.requeue()

        return HttpResponse(status=202)

    @list_route(methods=['post'])
    def collect_other(self, request, pk=None):
        dat = request.data
        dat['api_url'] = settings.SERVERSHARK_API_URL
        dat['api_key'] = settings.API_KEY
        dat['substitutions'] = settings.SUBSTITUTIONS

        jt = VSJobType.objects.get(ident='collect_other')
        j = VSJob(job_type=jt, requested_by=request.user)
        j.data = json.dumps(dat)
        j.save()

        return HttpResponse(status=202)

    @list_route(methods=['post'])
    def collect_revision(self, request, pk=None):

        # enrich with our data
        dat = request.data
        dat['api_url'] = settings.SERVERSHARK_API_URL
        dat['api_key'] = settings.API_KEY
        dat['substitutions'] = settings.SUBSTITUTIONS

        jt = VSJobType.objects.get(ident='collect_revision')
        j = VSJob(job_type=jt, requested_by=request.user)
        j.data = json.dumps(dat)
        j.save()

        return HttpResponse(status=202)

    @list_route(methods=['post'])
    def test_connection_servershark(self, request, pk=None):

        dat = request.data
        dat['api_url'] = settings.SERVERSHARK_API_URL
        dat['api_key'] = settings.API_KEY
        dat['substitutions'] = settings.SUBSTITUTIONS

        jt = VSJobType.objects.get(ident='test_connection_servershark')
        j = VSJob(job_type=jt, requested_by=request.user)
        j.data = json.dumps(dat)
        j.save()

        return HttpResponse(status=202)

    @list_route(methods=['post'])
    def test_connection_worker(self, request, pk=None):
        dat = request.data
        jt = VSJobType.objects.get(ident='test_connection_worker')
        j = VSJob(job_type=jt, requested_by=request.user)
        j.data = json.dumps(dat)
        j.save()

        return HttpResponse(status=202)


class IssueLabelSet(APIView):

    read_perm = 'view_issue_labels'
    write_perm = 'edit_issue_labels'

    def get(self, request):
        result = {}
        result['options'] = set(list(TICKET_TYPE_MAPPING.values()))
        result['issues'] = []
        linked = request.GET["linked"] == "true"

        # we need this to construct the URL
        if 'issue_system_id' in request.GET.keys():
            issue_system = IssueSystem.objects.get(id=request.GET["issue_system_id"])
        else:
            issue_system = IssueSystem.objects.get(project_id=request.GET['project_id'])

        if 'jira' in issue_system.url:
            base_url = 'https://issues.apache.org/jira/browse/'
        elif 'github' in issue_system.url:
            base_url = issue_system.url.replace('/repos/', '/').replace('api.', '')
            if not base_url.endswith('/'):
                base_url += '/'

        # we need this for the commit urls
        vcs = VCSSystem.objects.get(project_id=issue_system.project_id)
        vcs_url = vcs.url.replace('.git', '') + '/commit/'

        issue_query = IssueValidation.objects.filter(issue_system_id=issue_system.id, linked=linked)
        if request.GET["issue_type"] != "all":
            issue_query = issue_query.filter(issue_type_unified=request.GET["issue_type"])
        if request.GET["labeled_by_other_user"] == "true":
            issue_query = issue_query.filter(issuevalidationuser__isnull=False).exclude(issuevalidationuser__user__username=str(request.user))
        else:
            issue_query = issue_query.filter(issuevalidationuser__isnull=True)

        result['max'] = issue_query.count()
        issue_query = issue_query.order_by('?')[:10]

        issue_ids = []
        for iv in issue_query:
            issue_ids.append(iv.issue_id)

        issue_id_links = {}
        for c in Commit.objects.filter(vcs_system_id=vcs.id, linked_issue_ids__in=issue_ids):
            for iid in c.linked_issue_ids:
                key = str(iid)
                if key not in issue_id_links.keys():
                    issue_id_links[key] = []

                issue_id_links[key].append({'link': '{}{}'.format(vcs_url, c.revision_hash), 'name': c.revision_hash[:7]})

        for issue_id in issue_ids:
            issue = Issue.objects.get(id=issue_id)
            serializer = IssueLabelSerializer(issue, many=False)
            data = serializer.data
            data['url'] = base_url + issue.external_id

            if str(issue_id) not in issue_id_links.keys():
                data['links'] = []
            else:
                data['links'] = issue_id_links[str(issue_id)]
            if issue.issue_type is None:
                data['resolution'] = "other"
            else:
                data['resolution'] = TICKET_TYPE_MAPPING.get(issue.issue_type.lower().strip())
            result['issues'].append(data)

        return Response(result)

    def post(self, request):
        for issue in request.data:
            if 'checked' in issue and issue['checked'] is True:
                issue_db = Issue.objects.get(id=issue['id'])
                if issue_db.issue_type_manual is None:
                    issue_db.issue_type_manual = {}
                issue_db.issue_type_manual.update({str(request.user): issue["resolution"]})
                issue_db.save()

                # Update the cache
                validation = IssueValidation.objects.get(issue_id=issue['id'])
                issueValidationUser, created = IssueValidationUser.objects.get_or_create(
                    user=request.user,
                    issue_validation=validation,
                    label=issue["resolution"]
                )
                issueValidationUser.save()
                log.info('[ISSUE LABELING] user {} labeled issue {} as {}'.format(request.user, issue['id'], issue['resolution']))
        result = {}
        result['status'] = "ok"
        return Response(result)


class IssueConflictSet(APIView):
    read_perm = 'view_issue_conflicts'
    write_perm = 'edit_issue_conflicts'

    def get(self, request):
        result = {}
        result['options'] = set(list(TICKET_TYPE_MAPPING.values()))
        result['issues'] = []

        # we need this to construct the URL
        if 'issue_system_id' in request.GET.keys():
            issue_system = IssueSystem.objects.get(id=request.GET["issue_system_id"])
        else:
            issue_system = IssueSystem.objects.get(project_id=request.GET['project_id'])

        if 'jira' in issue_system.url:
            base_url = 'https://issues.apache.org/jira/browse/'
        elif 'github' in issue_system.url:
            base_url = issue_system.url.replace('/repos/', '/').replace('api.', '')
            if not base_url.endswith('/'):
                base_url += '/'

        # we need this for the commit urls
        vcs = VCSSystem.objects.get(project_id=issue_system.project_id)
        vcs_url = vcs.url.replace('.git', '') + '/commit/'

        linked = request.GET["linked"] == "true"

        # query construction
        issue_query = IssueValidation.objects.filter(issue_system_id=issue_system.id, linked=linked, resolution=False)
        if request.GET["issue_type"] != "all":
            issue_query = issue_query.filter(issue_type_unified=request.GET["issue_type"])

        # There muss be a validation
        issue_query = issue_query.filter(issuevalidationuser__isnull=False)
        result['max'] = issue_query.count()
        # issue_query = issue_query.order_by('?')

        issue_ids = []
        for iv in issue_query:
            # Check if all the same, then skip
            labels = IssueValidationUser.objects.filter(issue_validation=iv).values_list('label', flat=True)
            if len(set(labels)) == 1:
                result['max'] -= 1
                continue

            if iv.issue_id not in issue_ids:
                issue_ids.append(iv.issue_id)
            else:
                result['max'] -= 1

        issue_id_links = {}
        for c in Commit.objects.filter(vcs_system_id=vcs.id, linked_issue_ids__in=issue_ids):
            for iid in c.linked_issue_ids:
                key = str(iid)
                if key not in issue_id_links.keys():
                    issue_id_links[key] = []

                issue_id_links[key].append({'link': '{}{}'.format(vcs_url, c.revision_hash), 'name': c.revision_hash[:7]})

        for issue_id in issue_ids[:10]:
            issue = Issue.objects.filter(id=issue_id).first()
            serializer = IssueLabelConflictSerializer(issue, many=False)
            data = serializer.data
            data['url'] = base_url + issue.external_id

            if str(issue_id) not in issue_id_links.keys():
                data['links'] = []
            else:
                data['links'] = issue_id_links[str(issue_id)]

            if issue.issue_type is None:
                data['resolution'] = "other"
            else:
                data['resolution'] = TICKET_TYPE_MAPPING.get(issue.issue_type.lower().strip())
            result['issues'].append(data)

        return Response(result)

    def post(self, request):
        for issue in request.data:
            if 'checked' in issue and issue['checked'] is True:
                issue_db = Issue.objects.get(id=issue['id'])
                issue_db.issue_type_manual['committee'] = issue['resolution']
                issue_db.issue_type_verified = issue["resolution"]
                issue_db.save()
                validation = IssueValidation.objects.filter(issue_id=issue['id'])[0]
                validation.resolution = True
                validation.save()
                log.info('[ISSUE RESOLUTION] user {} labeled issue {} as {}'.format(request.user, issue['id'], issue['resolution']))

        result = {}
        result['status'] = "ok"
        return Response(result)


# issue link means bug link in this case
class IssueLinkSet(APIView):
    read_perm = 'view_issue_links'
    write_perm = 'edit_issue_links'

    def get(self, request):
        result = {}
        result['commits'] = []
        limit = int(request.GET["limit"])
        vcs_system = VCSSystem.objects.get(project_id=request.GET['project_id'])
        query = Commit.objects.filter(Q(vcs_system_id=vcs_system.id)).filter(Q(validations__ne='issue_links')).filter(Q(labels__issueonly_bugfix=True) | Q(labels__adjustedszz_bugfix=True)).only('id', 'message', 'linked_issue_ids', 'labels', 'szz_issue_ids')
        result['max'] = query.count()
        commits = query.order_by('?')[:limit]
        for commit in commits:
            if (commit.linked_issue_ids is not None and len(commit.linked_issue_ids)) > 0 or (commit.szz_issue_ids is not None and len(commit.szz_issue_ids) > 0):
                result_commit = {}
                result_commit["id"] = str(commit.id)
                result_commit["message"] = commit.message

                search = []
                if commit.linked_issue_ids:
                    for issue_id in commit.linked_issue_ids:
                        search.append(issue_id)
                if commit.szz_issue_ids:
                    for issue_id in commit.szz_issue_ids:
                        if issue_id not in search:
                            search.append(issue_id)

                issues = Issue.objects.filter(id__in=search)
                result_commit["links"] = [issue.external_id for issue in issues]
                result_commit["selected_links"] = [issue.external_id for issue in issues]
                result['commits'].append(result_commit)

        return Response(result)

    def post(self, request):
        for commit in request.data:
            commit_db = Commit.objects.get(id=commit["id"])
            issues = Issue.objects.filter(external_id__in=commit["selected_links"])
            linked_ids = [issue.id for issue in issues]
            commit_db.fixed_issue_ids = linked_ids
            if commit_db.validations is None:
                commit_db.validations = ["issue_links"]
            else:
                commit_db.validations.append("issue_links")
            commit_db.save()

        result = {}
        result['status'] = "ok"
        return Response(result)


class LineLabelSet(APIView):
    read_perm = 'view_line_labels'
    write_perm = 'edit_line_labels'

    def _open_issues(self):
        issue_ids = []
        for up in UserProfile.objects.all():
            if up.line_label_last_issue_id:
                issue_ids.append(up.line_label_last_issue_id)
        return issue_ids

    def _label_users(self, issue):
        """Return all users which have labeled this issue"""
        users = set()

        for c in Commit.objects.filter(fixed_issue_ids=issue.id).only('id', 'parents'):
            if c.parents:
                fa_qry = FileAction.objects.filter(commit_id=c.id, parent_revision_hash=c.parents[0])
            else:
                fa_qry = FileAction.objects.filter(commit_id=c.id)

            for fa in fa_qry:
                for h in Hunk.objects.filter(file_action_id=fa.id):
                    for user, lines in h.lines_manual.items():
                        users.add(user)
        return list(users)

    def _sample_issue(self, user, project_name):
        """Sample issue for user:

        An issue is sampled under these conditions:
            - is fixed in at least one commit
            - has less than 4 labels (including currently running!)
            - has verified_type bug
            - the user has not labeld it before
        """
        p = Project.objects.get(name=project_name)
        its = IssueSystem.objects.get(project_id=p.id)

        issues = list(Issue.objects.filter(issue_system_id=its.id, issue_type_verified='bug').order_by('?'))
        random.shuffle(issues)
        
        issue = None
        for i in issues:
            
            # only consider issues which are linked to bug_fixing commits
            if Commit.objects.filter(fixed_issue_ids=i.id).count() > 0:
                users = self._label_users(i)
                
                # skip issue if we already labeled it
                if user in users:
                    continue

                open_issues = self._open_issues()

                # skip issue if it exceeds 4 labelers including unfinished issues
                if len(users) + open_issues.count(str(i.id)) >= 4:
                    continue

                # use this issue
                issue = i
                break

        # overwrite sampling
        #issue = Issue.objects.get(id='5ca34d6c336b19134def9af2')
        return issue

    def _commit_data(self, issue, project_path):
        commits = []

        folder = tempfile.mkdtemp()
        git.repo.base.Repo.clone_from(project_path + "/", folder)

        for commit in Commit.objects.filter(fixed_issue_ids=issue.id).only('id', 'revision_hash', 'parents', 'message'):
            repo = git.Repo(folder)
            repo.git.reset('--hard', commit.revision_hash)

            if commit.parents:
                fa_qry = FileAction.objects.filter(commit_id=commit.id, parent_revision_hash=commit.parents[0])
            else:
                fa_qry = FileAction.objects.filter(commit_id=commit.id)

            # print('commit', commit.revision_hash)
            changes = []
            for fa in fa_qry:
                f = File.objects.get(id=fa.file_id)

                source_file = folder + '/' + f.path
                if not os.path.exists(source_file):
                    #print('file', source_file, 'not existing, skipping')
                    continue

                #print('open file', source_file, end='')
                # use libmagic to guess encoding
                blob = open(source_file, 'rb').read()
                m = magic.Magic(mime_encoding=True)
                encoding = m.from_buffer(blob)
                #print('encoding', encoding)
                
                # we open everything but binary
                if encoding == 'binary':
                    continue
                if encoding == 'unknown-8bit':
                    continue


                nfile = open(source_file, 'rb').read().decode(encoding)
                nfile = nfile.replace('\r\n', '\n')
                nfile = nfile.replace('\r', '\n')
                nfile = nfile.split('\n')
                view_lines, has_changed, lines_before, lines_after = get_change_view(nfile, Hunk.objects.filter(file_action_id=fa.id))

                if has_changed:
                    changes.append({'filename': f.path, 'lines': view_lines, 'parent_revision_hash': fa.parent_revision_hash, 'before': "\n".join(lines_before), 'after': "\n".join(lines_after)})

            commits.append({'revision_hash': commit.revision_hash, 'message': commit.message, 'changes': changes})

        shutil.rmtree(folder)
        return commits

    def post(self, request):
        issue_id = request.data['data']['issue_id']
        labels = request.data['data']['labels']
        type = request.data['type']
        issue = Issue.objects.get(id=issue_id)

        its = IssueSystem.objects.get(id=issue.issue_system_id)
        p = Project.objects.get(id=its.project_id)
        vcs = VCSSystem.objects.get(project_id=p.id)

        project_path = settings.LOCAL_REPOSITORY_PATH + p.name

        # check if we have a label for every line that is deleted
        commits = self._commit_data(issue, project_path)
        new_changes = []
        errors = []
        for c in commits:
            for change in c['changes']:
                key = c['revision_hash'] + '_' + change['parent_revision_hash'] + '_' + change['filename']
                label_lines = {}

                # load all lines that need a label
                lines_needing_labels = []
                for line in change['lines']:
                    if line['old'] == '-' or line['new'] == '-':
                        lines_needing_labels.append(line)

                # check if every line that needs a label is in submitted labels and has a label
                for line in lines_needing_labels:
                    line_number = str(line['number'])

                    if type == 'old_new':
                        line_number = str(line['old'])
                        if line_number == '-':
                            line_number = str(line['new'])

                    if line_number in labels[key] and labels[key][line_number] != 'label':
                        if line['hunk_id'] not in label_lines.keys():
                            label_lines[line['hunk_id']] = []

                        label_lines[line['hunk_id']].append({'label': labels[key][line_number], 'hunk_line': line['hunk_line'], 'line': line['code']})
                        # label_lines[line_number] = {'label': labels[key][line_number], 'user': request.user.username, 'hunk_id': line['hunk_id'], 'hunk_line': line['hunk_line']}
                    else:
                        errors.append('error, line {} not found or wrong label in key {}'.format(line_number, key))

                tmp = {key: label_lines}
                # tmp['labels'] = label_lines
                new_changes.append(tmp)
        if errors:
            print(errors)
            return Response({'statusText': '\n'.join(errors)}, status=status.HTTP_400_BAD_REQUEST)  # does not work

        # now save the final changes
        for change in new_changes:
            for key, changes in change.items():
                revision_hash, parent_revision_hash, file_name = key.split('_')[0], key.split('_')[1], '_'.join(key.split('_')[2:])  # ugly :-(

                # these are just sanity checks, the only important informaiton is the hunk_id
                c = Commit.objects.get(revision_hash=revision_hash, vcs_system_id=vcs.id)
                f = File.objects.get(path=file_name, vcs_system_id=vcs.id)
                fa = FileAction.objects.get(commit_id=c.id, file_id=f.id, parent_revision_hash=parent_revision_hash)

                write_changes = {}
                for hunk_id, lines in changes.items():
                    if hunk_id not in write_changes.keys():
                        write_changes[hunk_id] = {}
                        write_changes[hunk_id][request.user.username] = {}
                    for line in lines:
                        if line['label'] not in write_changes[hunk_id][request.user.username].keys():
                            write_changes[hunk_id][request.user.username][line['label']] = []
                        write_changes[hunk_id][request.user.username][line['label']].append(line['hunk_line'])

                for hunk_id, result in write_changes.items():
                    r = {'set__lines_manual__{}'.format(request.user.username): result[request.user.username]}
                    h = Hunk.objects.get(id=hunk_id).update(**r)

        # reset the issue id for sucessful labeling
        up = UserProfile.objects.get(user=request.user)
        up.line_label_last_issue_id = ''
        up.save()

        print('final changes')
        print(new_changes)
        return Response({'changes': new_changes})


    def get(self, request):
        
        project_name = request.GET.get('project_name', None)
        if not project_name:
            log.error('got no project')
            return Response({}, status=status.HTTP_400_BAD_REQUEST)

        # if the user has no last_issue_id sample one
        load_last = False
        if not request.user.profile.line_label_last_issue_id:
            issue = self._sample_issue(request.user.username, project_name)
            
            if issue:
                up = UserProfile.objects.get(user=request.user)
                up.line_label_last_issue_id = issue.id
                up.save()

        # otherwise use the last unfinished one
        else:
            print('loading last issue', request.user.profile.line_label_last_issue_id)
            issue = Issue.objects.get(id=request.user.profile.line_label_last_issue_id)
            load_last = True

        if issue == None:
            return Response({'warning': 'no_more_issues'})

        # urls for issue system and git
        issue_system = IssueSystem.objects.get(id=issue.issue_system_id)
        p = Project.objects.get(id=issue_system.project_id)
        if 'jira' in issue_system.url:
            issue_url = 'https://issues.apache.org/jira/browse/'
        elif 'github' in issue_system.url:
            issue_url = issue_system.url.replace('/repos/', '/').replace('api.', '')
            if not issue_url.endswith('/'):
                issue_url += '/'

        vcs = VCSSystem.objects.get(project_id=issue_system.project_id)
        vcs_url = vcs.url.replace('.git', '') + '/commit/'

        project_path = settings.LOCAL_REPOSITORY_PATH + p.name

        if not os.path.exists(project_path):
            log.error('no such path ' + project_path)
            return Response({}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        result = {'warning': '', 'commits': self._commit_data(issue, project_path), 'issue_url': issue_url, 'vcs_url': vcs_url, 'has_trained': request.user.profile.line_label_has_trained, 'load_last': load_last}

        serializer = IssueSerializer(issue, many=False)
        data = serializer.data
        result['issue'] = data

        return Response(result)

# tutorial issues:
# -  IMAGING-99 
# - imaging-82
# -imaging-121
# - codec-65
class LeaderboardSet(APIView):
    read_perm = 'view_line_labels'

    def get(self, request):
        lb = LeaderboardSnapshot.objects.order_by('-created_at')[0]
        return Response({'board': json.loads(lb.data), 'last_updated': lb.created_at})