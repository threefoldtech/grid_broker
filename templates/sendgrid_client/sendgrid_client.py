import sendgrid
from sendgrid.helpers.mail import Email, Content, Mail

from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.service_collection import ServiceNotFoundError


class SendgridClient(TemplateBase):

    version = '0.0.1'
    template_name = "sendgrid_client"

    def __init__(self, name, guid=None, data=None):
        super().__init__(name=name, guid=guid, data=data)
        self._client = None

    def validate(self):
        if not self.data.get('apiKey'):
            raise ValueError('apiKey needs to be specified')

    @property
    def _sg(self):
        if self._client is None:
            self._client = sendgrid.SendGridAPIClient(apikey=self.data['apiKey'])
        return self._client

    def send(self, sender, receiver, subject, content):
        from_email = Email(sender)
        to_email = Email(receiver)
        content = Content("text/html", content)
        mail = Mail(from_email, subject, to_email, content)
        _ = self._sg.client.mail.send.post(request_body=mail.get())
        self.logger.info('email send to %s', receiver)
