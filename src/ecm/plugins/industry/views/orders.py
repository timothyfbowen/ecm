# Copyright (c) 2010-2012 Robin Jarry
#
# This file is part of EVE Corporation Management.
#
# EVE Corporation Management is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# EVE Corporation Management is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# EVE Corporation Management. If not, see <http://www.gnu.org/licenses/>.

__date__ = "2011 8 19"
__author__ = "diabeteman"


try:
    import json
except ImportError:
    # fallback for python 2.5
    import django.utils.simplejson as json

from django.http import Http404, HttpResponseBadRequest, HttpResponse
from django.template.context import RequestContext
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render_to_response, redirect
from django.utils.text import truncate_words

from ecm.views import extract_datatable_params
from ecm.core import utils
from ecm.plugins.industry.models import Order, CatalogEntry

#------------------------------------------------------------------------------
COLUMNS = [
    ['#', 'id'],
    ['State', 'stateText'],
    ['Originator', 'originator'],
    ['Client', 'client'],
    ['Delivery Date', 'deliveryDate'],
    ['Items', None],
    ['Quote', 'quote'],
]
@login_required
def orders(request):
    columns = [ col[0] for col in COLUMNS ]
    return render_to_response('orders_list.html', {'columns' : columns}, RequestContext(request))

#------------------------------------------------------------------------------
@login_required
def orders_data(request):
    try:
        params = extract_datatable_params(request)
    except Exception, e:
        return HttpResponseBadRequest(str(e))

    query = Order.objects.all()

    orders = []
    for order in query:
        items = [ row.catalogEntry.typeName for row in order.rows.all() ]
        if order.deliveryDate is not None:
            delivDate = utils.print_date(order.deliveryDate)
        else:
            delivDate = '(none)'
        orders.append([
            order.permalink,
            order.stateText,
            order.originator_permalink,
            order.client or '(none)',
            delivDate,
            truncate_words(', '.join(items), 6),
            utils.print_float(order.quote),
        ])

    json_data = {
        "sEcho" : params.sEcho,
        "iTotalRecords" : len(orders),
        "iTotalDisplayRecords" : len(orders),
        "aaData" : orders
    }

    return HttpResponse(json.dumps(json_data))

#------------------------------------------------------------------------------
@login_required
def details(request, order_id):
    try:
        order = get_object_or_404(Order, id=int(order_id))
    except ValueError:
        raise Http404()

    logs = order.logs.all().order_by('-date')
    validTransitions = [ (trans.id, trans.text) for trans in order.validTransitions ]


    data = {'order' : order, 'logs': logs, 'validTransitions' : validTransitions}

    return render_to_response('order_details.html', data, RequestContext(request))


#------------------------------------------------------------------------------
@login_required
def change_state(request, order_id, transition):
    try:
        order = get_object_or_404(Order, id=int(order_id))
    except ValueError:
        raise Http404()
    if transition == Order.modify.id: #@UndefinedVariable
        return modify(request, order)
    elif transition == Order.confirm.id: #@UndefinedVariable
        order.confirm()
        return redirect('/shop/orders/%d/' % order.id)

#------------------------------------------------------------------------------
def modify(request, order):
    if request.method == 'POST':
        items, valid_order = extract_order_items(request)
        if valid_order:
            order.modify(items)
            return redirect('/industry/orders/%d/' % order.id)
    return render_to_response('order_modify.html', {'order': order}, RequestContext(request))

#------------------------------------------------------------------------------
def extract_order_items(request):
    items = []
    valid_order = True
    for key, value in request.POST.items():
        try:
            typeID = int(key)
            quantity = int(value)
            item = CatalogEntry.objects.get(typeID=typeID)
            if item.isAvailable:
                items.append( (item, quantity) )
            else:
                valid_order = False
        except ValueError:
            pass
        except CatalogEntry.DoesNotExist:
            valid_order = False
    return items, valid_order

