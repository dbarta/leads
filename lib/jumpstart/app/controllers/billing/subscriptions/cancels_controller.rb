class Billing::Subscriptions::CancelsController < ApplicationController
  before_action :authenticate_user!
  before_action :require_current_account_admin
  before_action :set_subscription

  layout "sidebar"

  def show
  end

  def destroy
    # Metered subscriptions should end immediately so they don't rack up more charges
    if @subscription.metered?
      @subscription.cancel_now!(invoice_now: true)

    # Unpaid subscriptions are treated as canceled, so end them immediately
    elsif @subscription.unpaid? || @subscription.past_due?
      @subscription.cancel_now!

    else
      # Cancel at period end
      @subscription.cancel
    end

    AccountMailer.with(subscription: @subscription, user: current_user).cancellation_reason.deliver_later(wait: 1.hour)

    redirect_to billing_path, status: :see_other
  rescue Pay::Error => e
    flash[:alert] = e.message
    render :show, status: :unprocessable_content
  end

  private

  def set_subscription
    @subscription = current_account.pay_subscriptions.find_by_prefix_id!(params[:subscription_id])
  rescue ActiveRecord::RecordNotFound
    redirect_to billing_path
  end
end
