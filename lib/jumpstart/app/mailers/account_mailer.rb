class AccountMailer < ApplicationMailer
  before_action :ensure_subscription_canceled, only: :cancellation_reason

  # Subject can be set in your I18n file at config/locales/en.yml
  # with the following lookup:
  #
  #   en.account_invitations_mailer.invite.subject
  #
  def invite
    @account_invitation = params[:account_invitation]
    @account = @account_invitation.account
    @invited_by = @account_invitation.invited_by || User.new(name: "Someone")

    mail(
      to: email_address_with_name(@account_invitation.email, @account_invitation.name),
      from: email_address_with_name(Jumpstart.config.support_email, Jumpstart.config.application_name),
      subject: t(".subject", inviter: @invited_by.name, account: @account.name)
    )
  end

  def cancellation_reason
    @account = @subscription.customer.owner
    @application_name = Jumpstart.config.application_name

    mail(
      to: (@account.admins.map(&:email) | [@account.email]).compact_blank,
      from: email_address_with_name(Jumpstart.config.support_email, @application_name),
      reply_to: Jumpstart.config.support_email,
      subject: t(".subject", application_name: @application_name)
    )
  end

  private

  def ensure_subscription_canceled
    @subscription = params[:subscription]

    # Don't send if subscription was resumed since this email was queued up
    throw :abort unless @subscription.canceled?
  end
end
