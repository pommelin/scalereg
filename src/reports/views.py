# Create your views here.

from django.contrib.auth.decorators import login_required
from django.db.models import BooleanField
from django.db.models.base import ModelBase
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response
from django.template import loader
from django.views.generic.list_detail import object_list as django_object_list
from __future__ import division
from scale.auth_helper.models import Service
from scale.reg6 import models
import datetime
import inspect
import re
import string

class Filter:
  def __init__(self, name):
    self.name = name
    self.items = {}
    self.selected = -1

  def get_items(self):
    items = self.items.items()
    items.sort()
    return [v[1] for v in items]


class Item:
  def __init__(self, name, value):
    self.name = name
    self.value = value


class SurveyQuestion:
  def __init__(self, name):
    self.name = name
    self.answers = []


class Count:
  def __init__(self, name):
    self.name = name
    self.count = 0
    self.percentage = 0


class Attendee(Count):
  def __init__(self, name):
    Count.__init__(self, name)
    self.checked_in = 0


def paranoid_strip(value):
  valid_chars = string.ascii_letters + string.digits + '_'
  for c in value:
    if c not in valid_chars:
      raise ValueError
  return value

def reports_perm_checker(user, path):
  # figure out what services are available
  if user.is_superuser:
    return True

  services_user = Service.objects.filter(users=user)
  services_user = services_user.filter(active=True)

  services_group = []
  for f in user.groups.all():
    group_s = Service.objects.filter(groups=f)
    group_s = group_s.filter(active=True)
    for s in group_s:
      services_group.append(s)

  services = []
  for f in services_user:
    services.append(f)
  services = set(services + services_group)

  can_access = False
  for f in services:
    if re.compile('%s/.*' % f.url).match(path):
      can_access = True
      break
  return can_access

def get_model_list(user):
  perms = user.get_all_permissions()
  tables = [m[0] for m in inspect.getmembers(models, inspect.isclass)
             if type(m[1]) == ModelBase and m[1]._meta.admin]
  model_list = []
  for t in tables:
    if user.is_superuser or "reg6.view_%s" % t.lower() in perms:
      def foo(match):
        return '%s %s' % match.groups()
      name = re.sub('([a-z])([A-Z])', foo, t)
      if not name.endswith('s'):
        name = name + 's'
      url = t.lower() + '/'
      model_list.append({'name': name, 'url': url})
  return model_list

@login_required
def index(request):
  can_access = reports_perm_checker(request.user, request.path)
  if not can_access:
    return HttpResponseRedirect('/accounts/profile/')
  
  model_list = get_model_list(request.user)

  return render_to_response('reports/index.html',
    {'user': request.user, 'title': 'Reports', 'model_list': model_list})

@login_required
def object_list(request, queryset, paginate_by=None, page=None,
  allow_empty=False, template_name=None, template_loader=loader,
  extra_context=None, context_processors=None, template_object_name='object',
  mimetype=None):
  can_access = reports_perm_checker(request.user, request.path)
  if not can_access:
    return HttpResponseRedirect('/accounts/profile/')

  model_list = get_model_list(request.user)
  can_access = False
  for f in model_list:
    if re.compile('/reports/%s.*' % f['url']).match(request.path):
      can_access = True
      break
  if not can_access:
    return HttpResponseRedirect('/accounts/profile/')

  all_fields = [f.name for f in queryset.model._meta.fields]

  if not extra_context:
    extra_context = {}

  if 'title' not in extra_context:
    extra_context['title'] = queryset.model._meta.verbose_name_plural.title()

  if 'field_list' not in extra_context:
    extra_context['field_list'] = all_fields

  filter_select = {}
  for i in xrange(len(all_fields)):
    name = all_fields[i]
    filter = Filter(name)
    field_type = type(queryset.model._meta.fields[i])
    if field_type == BooleanField:
      filter.items[-1] = (Item('All', -1))
      filter.items[0] = (Item('False', 0))
      filter.items[1] = (Item('True', 1))
    else:
      continue
    filter_select[name] = filter

  urlparts = []
  for f in request.GET:
    if not f.startswith('filter__'):
      continue
    urlparts.append('%s=%s&' % (f, request.GET[f]))
    name = f[8:]
    field_type = type(queryset.model._meta.fields[all_fields.index(name)])
    if name and name in filter_select:
      if field_type == BooleanField:
        filter = filter_select[name]
        try:
          value = int(request.GET[f])
        except ValueError:
          continue
        if value in filter.items and value != -1:
          filter.selected = value
          query_string = '%s = %%s' % paranoid_strip(name)
          queryset = queryset.extra(where=[query_string], params=[value])
  extra_context['filter_select'] = filter_select.values()
  extra_context['urlpart'] = ''.join([part for part in urlparts])

  extra_context['numbers'] = queryset.count()

  return django_object_list(request, queryset, paginate_by, page, allow_empty,
    template_name, template_loader, extra_context, context_processors,
    template_object_name, mimetype)

@login_required
def dashboard(request):
  # FIXME figure out what perms are needed here
  if not request.user.is_superuser:
    return HttpResponseRedirect('/accounts/profile/')

  today = datetime.date.today()
  days_30 = today - datetime.timedelta(days=30)
  days_7 = today - datetime.timedelta(days=7)

  orders_data = {}
  orders_data['by_type'] = []
  orders = models.Order.objects.filter(valid=True)
  orders_data['numbers'] = orders.count()
  orders_data['revenue'] = sum([x.amount for x in orders])
  orders_30 = orders.filter(date__gt = days_30)
  orders_data['numbers_30'] = orders_30.count()
  orders_data['revenue_30'] = sum([x.amount for x in orders_30])
  orders_7 = orders_30.filter(date__gt = days_7)
  orders_data['numbers_7'] = orders_7.count()
  orders_data['revenue_7'] = sum([x.amount for x in orders_7])
  for pt in models.PAYMENT_CHOICES:
    orders_pt = orders.filter(payment_type=pt[0])
    data_pt = {}
    data_pt['name'] = pt[1]
    data_pt['numbers'] = orders_pt.count()
    orders_pt_30 = orders_pt.filter(date__gt = days_30)
    data_pt['numbers_30'] = orders_pt_30.count()
    orders_pt_7 = orders_pt_30.filter(date__gt = days_7)
    data_pt['numbers_7'] = orders_pt_7.count()
    orders_data['by_type'].append(data_pt)

  attendees_data = {}
  attendees = models.Attendee.objects.filter(valid=True)
  num_attendees = attendees.count()
  attendees_data['numbers'] = num_attendees
  attendees_data['checked_in'] = attendees.filter(checked_in=True).count()

  type_attendees_data = {}
  ticket_attendees_data = {}
  for att in attendees:
    att_type = att.badge_type.type
    if att_type not in type_attendees_data:
      type_attendees_data[att_type] = Attendee(att_type)
    type_attendees_data[att_type].count += 1
    if att.checked_in:
      type_attendees_data[att_type].checked_in += 1

    att_ticket = att.badge_type.name
    if att_ticket not in ticket_attendees_data:
      ticket_attendees_data[att_ticket] = Count(att_ticket)
    ticket_attendees_data[att_ticket].count += 1
  type_attendees_data = type_attendees_data.items()
  type_attendees_data.sort()
  type_attendees_data = [v[1] for v in type_attendees_data]
  for t in type_attendees_data:
    t.percentage = 100 * round(t.count / float(num_attendees), 3)
  ticket_attendees_data = ticket_attendees_data.items()
  ticket_attendees_data.sort()
  ticket_attendees_data = [v[1] for v in ticket_attendees_data]
  for t in ticket_attendees_data:
    t.percentage = 100 * round(t.count / float(num_attendees), 3)

  promo_attendees_data = {}
  promo_attendees_data[None] = Count('None')
  for att in attendees:
    if att.promo:
      promo = att.promo.name
    else:
      promo = None
    if promo not in promo_attendees_data:
      promo_attendees_data[promo] = Count(promo)
    promo_attendees_data[promo].count += 1
  promo_attendees_data = promo_attendees_data.items()
  promo_attendees_data.sort()
  promo_attendees_data = [v[1] for v in promo_attendees_data]
  for p in promo_attendees_data:
    p.percentage = 100 * round(p.count / float(num_attendees), 3)

  zipcode_orders_data = {}
  for x in orders:
    if x.zip not in zipcode_orders_data:
      zipcode_orders_data[x.zip] = Count(x.zip)
    zipcode_orders_data[x.zip].count += 1
  zipcode_orders_data = zipcode_orders_data.items()
  zipcode_orders_data.sort()
  zipcode_orders_data = [v[1] for v in zipcode_orders_data]
  for zip in zipcode_orders_data:
    zip.percentage = 100 * round(zip.count / float(orders_data['numbers']), 3)

  zipcode_attendees_data = {}
  for att in attendees:
    if att.zip not in zipcode_attendees_data:
      zipcode_attendees_data[att.zip] = Count(att.zip)
    zipcode_attendees_data[att.zip].count += 1
  zipcode_attendees_data = zipcode_attendees_data.items()
  zipcode_attendees_data.sort()
  zipcode_attendees_data = [v[1] for v in zipcode_attendees_data]
  for zip in zipcode_attendees_data:
    zip.percentage = 100 * round(zip.count / float(num_attendees), 3)

  questions_data = []
  questions = models.Question.objects.all()

  all_answers = {}
  for ans in models.Answer.objects.all():
    all_answers[ans.text] = Count(ans.text)

  for att in attendees:
    for ans in att.answers.all():
      all_answers[ans.text].count += 1

  for q in questions:
    possible_answers = q.answer_set.all()
    q_data = SurveyQuestion(q.text)
    for ans in possible_answers:
      a_data = all_answers[ans.text]
      a_data.percentage = 100 * round(a_data.count / float(num_attendees), 3)
      q_data.answers.append(a_data)
    a_data = Count('No Answer')
    a_data.count = num_attendees - sum([x.count for x in q_data.answers])
    a_data.percentage = 100 * round(a_data.count / float(num_attendees), 3)
    q_data.answers.append(a_data)
    questions_data.append(q_data)

  return render_to_response('reports/dashboard.html',
    {'title': 'Dashboard',
     'attendees': attendees_data,
     'orders': orders_data,
     'promo_attendees': promo_attendees_data,
     'questions': questions_data,
     'ticket_attendees': ticket_attendees_data,
     'type_attendees': type_attendees_data,
     'zipcode_attendees': zipcode_attendees_data,
     'zipcode_orders': zipcode_orders_data,
    })

@login_required
def reg6log(request):
  if not request.user.is_superuser:
    return HttpResponseRedirect('/accounts/profile/')

  response = HttpResponse(mimetype='text/plain')
  try:
    f = open('/tmp/scale_reg.log')
    response.write(f.read())
    f.close()
  except:
    response.write('error reading log files\n')
  return response