require "test_helper"

class Users::RegistrationsControllerTest < ActionDispatch::IntegrationTest
  include InvisibleCaptcha

  setup do
    @user_params = {user:
                        {name: "Test User",
                         email: "user@test.com",
                         password: "TestPassword",
                         terms_of_service: "1"}}

    # With this feature enabled, we also need to submit an account
    if Jumpstart.config.register_with_account?
      @user_params[:user][:owned_accounts_attributes] = [{name: "Test Account"}]
    end
  end

  class BasicRegistrationTest < Users::RegistrationsControllerTest
    test "successfully registration form render" do
      get new_user_registration_path
      assert_response :success
      assert_includes response.body, "user[name]"
      assert_includes response.body, "user[email]"
      assert_includes response.body, "user[password]"
      assert_includes response.body, InvisibleCaptcha.sentence_for_humans
    end

    test "successful user registration" do
      assert_difference "User.count" do
        post user_registration_url, params: @user_params
      end
    end

    test "failed user registration" do
      assert_no_difference "User.count" do
        post user_registration_url, params: {}
      end
    end
  end

  class InvibleCaptchaTest < Users::RegistrationsControllerTest
    test "honeypot is not filled and user creation succeeds" do
      assert_difference "User.count" do
        post user_registration_url, params: @user_params.merge(honeypotx: "")
      end
    end

    test "honeypot is filled and user creation fails" do
      assert_no_difference "User.count" do
        post user_registration_url, params: @user_params.merge(honeypotx: "spam")
      end
    end
  end
end
