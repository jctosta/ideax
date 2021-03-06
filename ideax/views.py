from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Case, When
from .models import Idea, Criterion,Popular_Vote, Phase, Phase_History,Category, Comment, UserProfile, Dimension, Evaluation, Category_Image, Use_Term
from .forms import IdeaForm, CriterionForm,IdeaFormUpdate, CategoryForm, EvaluationForm, EvaluationForm
from .singleton import Profanity_Check
from django import forms
from wordfilter import Wordfilter
import os
import json
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.forms import modelformset_factory
import collections
from django.http import HttpResponse
from django.template.loader import get_template
from django.template import Context
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.decorators import permission_required
from django.core import mail
from django.core.mail import EmailMessage
from .mail_util import Mail_Util
import mistune
from .util import get_ip, get_client_ip
import logging

# Creating log object
logger = logging.getLogger('audit_log')

mail_util = Mail_Util()

def audit(username, ip_addr, operation, className, objectId):
    logger.info(
        '%(username)s|%(ip_addr)s|%(operation)s|%(className)s|%(objectId)s', 
        { 
            'username': username, 
            'ip_addr': ip_addr, 
            'operation': operation,
            'className': className,
            'objectId': objectId
        }
    )

def index(request):
    if request.user.is_authenticated:
        audit(request.user.username, get_client_ip(request), 'LIST_IDEAS_PAGE', Idea.__name__, '')
        return idea_list(request)
    return render(request, 'ideax/index.html')

def get_page_body(boxes):
    for box in boxes:
        if box.element_tag == 'body':
            return box
        return get_page_body(box.all_children())

@login_required
def accept_use_term(request):
    if not request.user.userprofile.use_term_accept:
        user_profile = UserProfile.objects.get(user=request.user)
        user_profile.use_term_accept = True
        user_profile.acceptance_date = timezone.localtime(timezone.now())
        user_profile.ip = get_ip(request)
        user_profile.save()
        messages.success(request, _('Term of use accepted!'))
        #logger.info('%(username)s|%(ip_addr)s|%(message)s', { 'username': request.user.username, 'ip_addr': get_client_ip(request), 'message': 'Term of use accepted!'})
    else:
        messages.success(request, _('Term of use already accepted!'))
        #logger.info('%(username)s|%(ip_addr)s|%(message)s', { 'username': request.user.username, 'ip_addr': get_client_ip(request), 'message': 'Term of use already accepted!'})

    audit(request.user.username, get_client_ip(request), 'ACCEPT_TERMS_OF_USE_OPERATION', UserProfile.__name__, '')
    return redirect('index')

@login_required
def idea_list(request):
    ideas = get_ideas_init(request)
    ideas['phases'] = Phase.choices()
    return render(request, 'ideax/idea_list.html', ideas)

@login_required
def get_ideas_init(request):
    ideas_dic = dict()
    ideas_dic['ideas'] = Idea.objects.filter(discarded=False, phase_history__current_phase=1, phase_history__current=1).annotate(count_like=Count(Case(When(popular_vote__like = True, then=1)))).order_by('-count_like')
    ideas_dic['ideas_liked'] = get_ideas_voted(request, True)
    ideas_dic['ideas_disliked'] = get_ideas_voted(request, False)
    ideas_dic['ideas_created_by_me'] = get_ideas_created(request)
    return ideas_dic

def get_phases():
    phase_dic = dict()
    phase_dic['phases'] = Phase.choices()
    return phase_dic

def idea_filter(request, phase_pk):
    #if phase_pk == 0:
    #    filtered_phases = Phase_History.objects.filter(current=1)
    #else:
    #    filtered_phases = Phase_History.objects.filter(current_phase=phase_pk, current=1)

    #ideas = [];
    #for phase in filtered_phases:
    #    if phase.idea.discarded == False:
    #        ideas.append(phase.idea)
    #ideas.sort(key=lambda idea:idea.creation_date)
    ideas =  Idea.objects.filter(discarded=False, phase_history__current_phase=phase_pk, phase_history__current=1).annotate(count_like=Count(Case(When(popular_vote__like = True, then=1)))).order_by('-count_like')
    context={'ideas': ideas,
             'ideas_liked': get_ideas_voted(request, True),
             'ideas_disliked': get_ideas_voted(request, False),
             'ideas_created_by_me' : get_ideas_created(request),}

    data = dict()
    data['html_idea_list'] = render_to_string('ideax/idea_list_loop.html', context, request=request)
    data['empty'] = 0

    if not ideas:
        data['html_idea_list'] = render_to_string('ideax/includes/empty.html', request=request)
        data['empty'] = 1
    return JsonResponse(data)

@login_required
def save_idea(request, form, template_name, new=False):
    data = dict()
    if request.method == "POST":
        if form.is_valid():
            idea = form.save(commit=False)
            if new:
                idea.author = UserProfile.objects.get(user=request.user)
                idea.creation_date = timezone.now()
                idea.phase= Phase.GROW.id
                category_image = Category_Image.get_random_image(idea.category)
                if category_image:
                    idea.category_image = category_image.image.url

                idea.save()
                phase_history = Phase_History(current_phase=Phase.GROW.id,
                                              previous_phase=0,
                                              date_change=timezone.now(),
                                              idea=idea,
                                              author=idea.author,
                                              current=True)
                phase_history.save()
            else:
                idea.save()
            messages.success(request, _('Idea saved successfully!'))
            
            audit(request.user.username, get_client_ip(request), 'SAVE_IDEA_OPERATION', Idea.__name__, str(idea.id))
            
            return redirect('idea_list')

    return render(request, template_name, {'form': form})

@login_required
@permission_required('ideax.add_idea',raise_exception=True)
def idea_new(request):
    if request.method == "POST":
        form = IdeaForm(request.POST)
    else:
        form = IdeaForm()

    audit(request.user.username, get_client_ip(request), 'CREATE_IDEA_FORM', Idea.__name__, '')
    
    return save_idea(request, form, 'ideax/idea_new.html', True)

@login_required
@permission_required('ideax.change_idea',raise_exception=True)
def idea_edit(request, pk):
    idea = get_object_or_404(Idea, pk=pk)

    if ((request.user.userprofile == idea.author and idea.get_current_phase() == Phase.GROW)
                    or request.user.has_perm(settings.PERMISSIONS["MANAGE_IDEA"])):
        if request.method == "POST":
            form = IdeaForm(request.POST, instance=idea)
        else:
            form = IdeaForm(instance=idea)
        
        audit(request.user.username, get_client_ip(request), 'EDIT_IDEA_FORM', Idea.__name__, str(idea.id))
        
        return save_idea(request, form, 'ideax/idea_edit.html')
    else:
        messages.error(request, _('Not supported action'))
        return redirect('index')

@login_required
@permission_required('ideax.delete_idea',raise_exception=True)
def idea_remove(request, pk):
    idea = get_object_or_404(Idea, pk=pk)
    data = dict()

    if ((request.user.userprofile == idea.author and idea.get_current_phase() == Phase.GROW)
                    or request.user.has_perm(settings.PERMISSIONS["MANAGE_IDEA"])):
        if request.method == 'POST':
            idea.discarded = True
            idea.save()
            data['form_is_valid'] = True
            ideas = get_ideas_init(request)
            data['html_list'] = render_to_string('ideax/idea_list_loop.html', ideas, request=request)
        else:
            context = {'idea' : idea}
            data['html_form'] = render_to_string('ideax/includes/partial_idea_remove.html',
                                                 context,
                                                 request=request,)

        audit(request.user.username, get_client_ip(request), 'REMOVE_IDEA_CONFIRMATION', Idea.__name__, str(idea.id))
        
        return JsonResponse(data)
    else:
        messages.error(request, _('Not supported action'))
        return redirect('index')

@login_required
@permission_required('ideax.add_criterion',raise_exception=True)
def criterion_new(request):
    if request.method == "POST":
        form = CriterionForm(request.POST)
        if form.is_valid():
            criterion = form.save(commit=False)
            criterion.save()

            audit(request.user.username, get_client_ip(request), 'CREATE_NEW_CRITERION_OPERATION', Criterion.__name__, str(criterion.id))

            return redirect('criterion_list')
    else:
        form = CriterionForm()

    return render(request, 'ideax/criterion_edit.html', {'form': form})

@login_required
@permission_required('ideax.add_criterion',raise_exception=True)
def criterion_list(request):
    criterion = Criterion.objects.all()
    audit(request.user.username, get_client_ip(request), 'CRITERION_LIST', Criterion.__name__, '')
    return render(request, 'ideax/criterion_list.html', {'criterions': criterion})

@login_required
@permission_required('ideax.change_criterion',raise_exception=True)
def criterion_edit(request, pk):
    criterion = get_object_or_404(Criterion, pk=pk)
    if request.method == "POST":
        form = CriterionForm(request.POST, instance=criterion)
        if form.is_valid():
            criterion = form.save(commit=False)
            criterion.save()

            audit(request.user.username, get_client_ip(request), 'EDIT_CRITERION_SAVE', Criterion.__name__, str(criterion.id))

            return redirect('criterion_list')
    else:
        form = CriterionForm(instance=criterion)

    return render(request, 'ideax/criterion_edit.html', {'form': form})

@login_required
@permission_required('ideax.add_evaluation',raise_exception=True)
def idea_evaluation(request, idea_pk):
    valuator = UserProfile.objects.get(user=request.user)
    idea = get_object_or_404(Idea, pk=idea_pk)

    idea_score = 0.0
    divisor = 0
    soma = 0

    dim = Dimension.objects.filter(final_date__isnull=True)

    data = dict()
    if request.POST:
        form_ = EvaluationForm(request.POST, extra=dim)
        if form_.is_valid() and request.user.userprofile.manager:
            for i in dim:
                divisor += i.weight
                dimension_value = i.weight * form_.cleaned_data[EvaluationForm.FORMAT_ID % i.pk].value
                soma += dimension_value
                if idea.score <= 0:
                    evaluation = Evaluation(valuator=valuator,
                                            idea=idea,
                                            dimension=i,
                                            category_dimension=form_.cleaned_data[EvaluationForm.FORMAT_ID % i.pk],
                                            evaluation_date=timezone.now(),
                                            dimension_value=dimension_value,
                                            note=form_.cleaned_data[EvaluationForm.FORMAT_ID_NOTE % i.pk],)
                else:
                    evaluation = Evaluation.objects.get(dimension=i, idea=idea)
                    evaluation.category_dimension = form_.cleaned_data[EvaluationForm.FORMAT_ID % i.pk]
                    evaluation.note = form_.cleaned_data[EvaluationForm.FORMAT_ID_NOTE % i.pk]
                    evaluation.dimension_value=dimension_value

                evaluation.save()

                audit(request.user.username, get_client_ip(request), 'CREATE_EVALUATION_SAVE', Evaluation.__name__, str(evaluation.id))

            idea_score = soma/divisor
            idea.score = idea_score
            idea.save()

            audit(request.user.username, get_client_ip(request), 'EDIT_IDEA_EVALUATION_SAVE', Idea.__name__, str(idea.id))

            data['score_value'] = idea_score
        else:
            data["msg"] = _("Something went wrong or you're not allowed!")
            return JsonResponse(data, status=500)
    else:
        form_ = EvaluationForm(extra=dim)

    data["msg"] = _("Evaluation done successfully!")
    return JsonResponse(data)

@login_required
def criterion_remove(request, pk):
    criterion = get_object_or_404(Criterion, pk=pk)

    criterion.delete()

    audit(request.user.username, get_client_ip(request), 'REMOVE_CRITERION_SAVE', Criterion.__name__, str(pk))
    
    return redirect('criterion_list')

def open_category_new(request, ):
    data = dict()
    context = {'form': CategoryForm()}
    data['html_form'] = render_to_string('ideax/category_new.html',
                                         context,
                                         request=request,)
    return JsonResponse(data)

@login_required
@permission_required('ideax.add_category',raise_exception=True)
def category_new(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
    else:
        form = CategoryForm()

    if request.is_ajax():
        return save_category(request, 'ideax/category_new.html', form)
    else:
        return redirect('category_list')

def save_category(request, template_name, form):
    data = dict()
    if request.method == "POST":
        if form.is_valid():
            category = form.save(commit=False)
            category.save()

            audit(request.user.username, get_client_ip(request), 'CATEGORY_SAVE', Category.__name__, str(category.id))

            data['form_is_valid'] = True
        else:
            data['form_is_valid'] = False

        data['html_list'] = render_to_string('ideax/includes/partial_category_list.html',
                                             get_category_list())
    context = {'form' : form}
    data['html_form'] = render_to_string(template_name, context, request=request,)

    return JsonResponse(data)

@login_required
@permission_required('ideax.change_category',raise_exception=True)
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
    else:
        form = CategoryForm(instance=category)

    return save_category(request,'ideax/category_edit.html',form)

@login_required
@permission_required('ideax.delete_category',raise_exception=True)
def category_remove(request, pk):
    category = get_object_or_404(Category, pk=pk)
    data = dict()
    if request.method == 'POST':
        category.discarded = True
        category.save()
        audit(request.user.username, get_client_ip(request), 'REMOVE_CATEGORY_SAVE', Category.__name__, str(category.id))
        data['form_is_valid'] = True
        data['html_list'] = render_to_string('ideax/includes/partial_category_list.html',
                                             get_category_list())
    else:
        context = {'category': category}
        data['html_form'] = render_to_string('ideax/includes/partial_category_remove.html',
                                             context,
                                             request=request)

    return JsonResponse(data)

def category_list(request):
    audit(request.user.username, get_client_ip(request), 'CATEGORY_LIST', Category.__name__, '')
    return render(request, 'ideax/category_list.html', get_category_list())


def get_category_list():
    return {'category_list': Category.objects.filter(discarded=False)}

@login_required
@permission_required('ideax.add_popular_vote',raise_exception=True)
def like_popular_vote(request, pk):
    user = UserProfile.objects.get(user=request.user)
    vote = Popular_Vote.objects.filter(voter=user,idea__pk=pk)

    idea_ = Idea.objects.get(pk=pk)
    like_boolean =  request.path.split("/")[3] == "like"

    if vote.count() == 0:
        like = Popular_Vote(like=like_boolean,voter=user,voting_date=timezone.now(),idea=idea_)
        like.save()
        audit(request.user.username, get_client_ip(request), 'LIKE_SAVE', Popular_Vote.__name__, str(like.id))
    else:
        if vote[0].like == like_boolean:
            vote.delete()
            audit(request.user.username, get_client_ip(request), 'DISLIKE_SAVE', Popular_Vote.__name__, str(vote.id))
            like_boolean = None
        else:
            vote.update(like=like_boolean)

    data = dict()
    data['qtde_votes_likes'] = idea_.count_likes()
    data['qtde_votes_dislikes'] = idea_.count_dislikes()
    data['class'] = like_boolean

    return JsonResponse(data)

@login_required
def get_ideas_voted(request, vote):
    user = UserProfile.objects.get(user=request.user)
    ideas_voted = []
    if request.user.is_authenticated:
        ideas_voted = Popular_Vote.objects.filter(like=vote, voter=user).values_list('idea_id',flat=True)

    return ideas_voted

@login_required
def get_ideas_created(request):
    user = UserProfile.objects.get(user=request.user)
    ideas_created = []
    if request.user.is_authenticated:
        ideas_created = Idea.objects.filter(author=user).values_list('id',flat=True)

    return ideas_created

@login_required
@permission_required('ideax.add_phase_history',raise_exception=True)
def change_idea_phase(request, pk, new_phase):
    idea = Idea.objects.get(pk=pk)
    phase = Phase.get_phase_by_id(new_phase)

    if phase != None and request.user.userprofile.manager:
        phase_history_current = Phase_History.objects.get(idea=idea, current=True)
        phase_history_current.current = False
        phase_history_current.save()

        phase_history_new = Phase_History(current_phase=phase.id,
                                          previous_phase=phase_history_current.current_phase,
                                          date_change=timezone.now(),
                                          idea=idea,
                                          author=UserProfile.objects.get(user=request.user),
                                          current=True)
        phase_history_new.save()
        audit(request.user.username, get_client_ip(request), 'CHANGE_PHASE_SAVE', Phase.__name__, str(phase_history_new.id))
        messages.success(request, _('Phase change successfully!'))
        context = {}
        context['idea'] = idea
        mail_util.send_mail(mail_util.generate_messages("[IdeiaX] - " + str(_('Phase change')), 'ideax/phase_change_email.html', context, [idea.author.user.email]))

    return redirect('index')

@login_required
def idea_detail(request, pk):
    idea = get_object_or_404(Idea, pk=pk)
    comments = idea.comment_set.filter(deleted=False);

    data = dict()
    data["comments"] = comments
    data["idea"] = idea
    data["idea_id"] = idea.pk

    initial = collections.OrderedDict()
    form_ = None
    if idea.score > 0:
        for i in idea.evaluation_set.all().order_by('dimension__id'):
            initial[EvaluationForm.FORMAT_ID % i.dimension.pk] = i
            form_ = EvaluationForm(initial=initial)

    else:
        form_ = EvaluationForm(extra=Dimension.objects.filter(final_date__isnull=True))


    data["form_evaluation"] = None if not form_.fields else form_
    data["evaluation_detail"] = initial

    try:
        data["popular_vote"] = idea.popular_vote_set.get(voter=request.user.userprofile).like
    except Popular_Vote.DoesNotExist:
        pass

    return render(request, 'ideax/idea_detail.html', data)

@login_required
@permission_required('ideax.add_comment',raise_exception=True)
def post_comment(request):
    if not request.user.is_authenticated:
        return JsonResponse({'msg': _("You need to log in to post new comments.")}, status=500)

    raw_comment = request.POST.get('commentContent', None)
    parent_id = request.POST.get('parentId', None)
    author = UserProfile.objects.get(user=request.user)
    idea_id = request.POST.get('ideiaId', None)

    if Profanity_Check.wordcheck().search_badwords(raw_comment):
        return JsonResponse({'msg': _("Please check your message it has inappropriate content.")}, status=500)

    if not raw_comment:
        return JsonResponse({'msg': _("You have to write a comment.")},status=500)

    if not parent_id:
        parent_object = None
    else:
        parent_object = Comment.objects.get(id=parent_id)

    idea = Idea.objects.get(id=idea_id)

    comment = Comment(author=author,
                      raw_comment=mistune.markdown(raw_comment),
                      parent=parent_object,
                      idea=idea,
                      date=timezone.now(),
                      comment_phase=idea.get_current_phase().id,
                      ip=get_client_ip(request))

    comment.save()
    audit(request.user.username, get_client_ip(request), 'COMMENT_SAVE', Comment.__name__, str(comment.id))
    return JsonResponse({"msg" : _("Your comment has been posted.")})

def idea_comments(request, pk):
    data = dict()
    data['html_list'] = render_to_string('ideax/includes/partial_comments.html',
                                         {"comments" : Comment.objects.filter(idea__id=pk),
                                          "idea_id" : pk})
    return JsonResponse(data)

def get_term_of_user(request):
    term = Use_Term.objects.get(final_date__isnull=True)
    return JsonResponse({"term" : term.term })

def idea_detail_pdf(request, idea_id):
    idea = Idea.objects.get(pk=idea_id)
    data = dict()
    initial = collections.OrderedDict()
    data['idea'] = idea
    for i in idea.evaluation_set.all().order_by('dimension__id'):
        initial[EvaluationForm.FORMAT_ID % i.dimension.pk] = i

    data['evaluation_detail']= initial
    audit(request.user.username, get_client_ip(request), 'REPORT_GENERATE', Idea.__name__, str(idea.id))
    return render(request, 'ideax/ftec.html', data)
    #pdf_file = generate_pdf_report('ideax/ftec.html', request.build_absolute_uri(), data)
    #response = HttpResponse('pdf_file', content_type='text/plain')
    #response['Content-Disposition'] = 'filename="idea_report.txt"'
    #return response
