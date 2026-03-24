class Billing::Subscriptions::ResumesController < ApplicationController
  before_action :authenticate_user!
  before_action :require_current_account_admin
  before_action :set_subscription

  layout "sidebar"

  def show
  end

  def update
    @subscription.resume
    redirect_to billing_path
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
