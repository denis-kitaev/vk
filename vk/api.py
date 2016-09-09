# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import logging.config
import six
try:
    # Python2
    from urllib import urlencode
except ImportError:
    # Python3
    from urllib.parse import urlencode

import requests

from vk.logs import LOGGING_CONFIG
from vk.utils import stringify_values, json_iter_parse, LoggingSession
from vk.exceptions import VKAuthError, VKAPIError
from vk.mixins import AuthMixin, InteractiveMixin


VERSION = '2.0.2'


logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger('vk')


class Session(object):
    API_URL = 'https://api.vk.com/method/'

    def __init__(self, access_token=None):
        logger.debug(
            'API.__init__(access_token=%(access_token)r)',
            {'access_token': access_token})

        self.access_token = access_token
        self.access_token_is_needed = False

        self.requests_session = LoggingSession()
        self.requests_session.headers['Accept'] = 'application/json'
        self.requests_session.headers['Content-Type'] = 'application/x-www-form-urlencoded'

    @property
    def access_token(self):
        logger.debug('Check that we need new access token')
        if self.access_token_is_needed:
            logger.debug('We need new access token. Try to get it.')
            self.access_token = self.get_access_token()
        else:
            logger.debug('Use old access token')
        return self._access_token

    @access_token.setter
    def access_token(self, value):
        self._access_token = value
        if isinstance(value, six.text_type) and len(value) >= 12:
            self.censored_access_token = '{}***{}'.format(value[:4], value[-4:])
        else:
            self.censored_access_token = value
        logger.debug('access_token = %r', self.censored_access_token)
        self.access_token_is_needed = not self._access_token

    def get_user_login(self):
        logger.debug('Do nothing to get user login')

    def get_access_token(self):
        """
        Dummy method
        """
        logger.debug('API.get_access_token()')
        return self._access_token

    def make_request(self, method_request, captcha_response=None):
        logger.debug('Prepare API Method request')

        response = self.send_api_request(method_request, captcha_response=captcha_response)
        # todo Replace with something less exceptional
        response.raise_for_status()

        # there are may be 2 dicts in one JSON
        # for example: "{'error': ...}{'response': ...}"
        for response_or_error in json_iter_parse(response.text):
            if 'response' in response_or_error:
                # todo Can we have error and response simultaneously
                # for error in errors:
                #     logger.warning(str(error))

                return response_or_error['response']

            elif 'error' in response_or_error:
                error_data = response_or_error['error']
                error = VKAPIError(error_data)

                if error.is_captcha_needed():
                    captcha_key = self.get_captcha_key(error.captcha_img)
                    if not captcha_key:
                        raise error

                    captcha_response = {
                        'sid': error.captcha_sid,
                        'key': captcha_key,
                    }
                    return self.make_request(method_request, captcha_response=captcha_response)

                elif error.is_access_token_incorrect():
                    logger.info('Authorization failed. Access token will be dropped')
                    self.access_token = None
                    return self.make_request(method_request)

                else:
                    raise error

    def send_api_request(self, request, captcha_response=None):
        url = self.API_URL + request._method_name
        method_args = request.api._method_default_args.copy()
        method_args.update(stringify_values(request._method_args))
        access_token = self.access_token
        if access_token:
            method_args['access_token'] = access_token
        if captcha_response:
            method_args['captcha_sid'] = captcha_response['sid']
            method_args['captcha_key'] = captcha_response['key']
        timeout = request.api.timeout
        response = self.requests_session.post(url, method_args, timeout=timeout)
        return response

    def get_captcha_key(self, captcha_image_url):
        """
        Default behavior on CAPTCHA is to raise exception
        Reload this in child
        """
        return None
    
    def auth_code_is_needed(self, content, session):
        """
        Default behavior on 2-AUTH CODE is to raise exception
        Reload this in child
        """           
        raise VKAuthError('Authorization error (2-factor code is needed)')
    
    def auth_captcha_is_needed(self, content, session):
        """
        Default behavior on CAPTCHA is to raise exception
        Reload this in child
        """
        raise VKAuthError('Authorization error (captcha)')

    def phone_number_is_needed(self, content, session):
        """
        Default behavior on PHONE NUMBER is to raise exception
        Reload this in child
        """
        logger.error('Authorization error (phone number is needed)')
        raise VKAuthError('Authorization error (phone number is needed)')


class API(object):
    url = 'https://api.vk.com/method/'
    version = '5.53'

    def __init__(self, session, timeout=10):
        self._vk_session = session
        self._http_session = requests.Session()
        self._timeout = timeout
        self._method_default_args = method_default_args

    def __getattr__(self, namespace):
        return APINamespace(self, namespace)

    def _get_access_token(self):
        return ''

    def _get_url(self, method):
        query_dict = {
            'v': self.version,
            'access_token': self._get_access_token()
        }
        query_params = urlencode(query_dict)
        return '%s%s?%s' % (self.url, method, query_params)

    def call(self, method, **params):
        url = self._get_url(method)
        return self._http_session.post(url, json=params)


class APINamespace(object):
    """
    API namespace class
    """
    def __init__(self, api, name):
        self._api = api
        self._name = name

    def __getattr__(self, item):
        return APIMethod(self._api, self._name, item)


class APIMethod(object):
    def __init__(self, api, namespace, name):
        self._api = api
        self._namespace = namespace
        self._name = name

    def __call__(self, **params):
        self._api.call(self.method_name, **params)

    @property
    def method_name(self):
        return '%s.%s' % (self._namespace, self._name)


class AuthSession(AuthMixin, Session):
    pass


class InteractiveSession(InteractiveMixin, Session):
    pass


class InteractiveAuthSession(InteractiveMixin, AuthSession):
    pass
