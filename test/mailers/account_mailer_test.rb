require "test_helper"

class AccountMailerTest < ActionMailer::TestCase
  test "invite" do
    account_invitation = account_invitations(:one)
    mail = AccountMailer.with(account_invitation: account_invitation).invite
    assert_equal I18n.t("account_mailer.invite.subject", inviter: "User One", account: "Company"), mail.subject
    assert_equal [account_invitation.email], mail.to
    assert_equal [Mail::Address.new(Jumpstart.config.support_email).address], mail.from
    assert_match I18n.t("account_mailer.invite.view_invitation"), mail.body.encoded
  end

  test "cancellation_reason when resumed" do
    account = accounts(:one)
    subscription = Pay::FakeProcessor::Subscription.new(customer: Pay::Customer.new(owner: account))
    AccountMailer.with(subscription: subscription, user: account.owner).cancellation_reason.deliver_now
    assert_emails 1
  end
end
