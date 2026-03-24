require "test_helper"

class Jumpstart::MultitenancyTest < ActionDispatch::IntegrationTest
  setup do
    @user = users(:one)
    @account = accounts(:company)
    sign_in @user
  end

  test "domain multitenancy" do
    Jumpstart.config.stub(:account_types, "both") do
      Jumpstart::Multitenancy.stub :selected, ["subdomain"] do
        get about_path
        assert_select ".account-menu .name", text: @user.name

        host! @account.domain
        sign_in @user

        get about_path
        assert_select ".account-menu .name", text: @account.name
      end
    end
  end

  test "subdomain multitenancy" do
    Jumpstart.config.stub(:account_types, "both") do
      Jumpstart::Multitenancy.stub :selected, ["subdomain"] do
        get about_path
        assert_select ".account-menu .name", text: @user.name

        host! "#{@account.subdomain}.example.com"
        sign_in @user

        get about_path
        assert_select ".account-menu .name", text: @account.name
      end
    end
  end

  test "script path multitenancy" do
    Jumpstart.config.stub(:account_types, "both") do
      Jumpstart::Multitenancy.stub :selected, ["path"] do
        get about_path
        assert_select ".account-menu .name", text: @user.name

        get "/#{@account.id}/about"
        assert_select ".account-menu .name", text: @account.name
      end
    end
  end

  test "session multitenancy" do
    Jumpstart.config.stub(:account_types, "both") do
      Jumpstart::Multitenancy.stub :selected, [] do
        get about_path
        assert_select ".account-menu .name", text: @user.name

        switch_account(@account)

        get about_path
        assert_select ".account-menu .name", text: @account.name
      end
    end
  end
end
