class Users::PasswordsController < Devise::PasswordsController
  rate_limit to: 10, within: 3.minutes, only: :create, with: -> { redirect_to new_user_session_path, alert: I18n.t("try_again_later") }

  # TODO: Remove if this PR gets merged https://github.com/heartcombo/devise/pull/5653
  # This allows using a proc for the setting in devise.rb
  def sign_in_after_reset_password?
    setting = resource_class.sign_in_after_reset_password
    setting.respond_to?(:call) ? setting.call(resource) : setting
  end
end
