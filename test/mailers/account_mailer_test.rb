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
    subscription = Pay::FakeProcessor::Subscription.new(
      customer: Pay::Customer.new(owner: Account.first),
      ends_at: nil
    )
    assert_no_emails do
      AccountMailer.with(subscription: subscription).cancellation_reason.deliver_now
    end

    subscription.ends_at = 1.week.from_now
    assert_emails 1 do
      AccountMailer.with(subscription: subscription).cancellation_reason.deliver_now
    end
  end
end
