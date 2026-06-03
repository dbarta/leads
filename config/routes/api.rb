namespace :api, defaults: {format: :json} do
  namespace :v1 do
    resource :auth, only: [:create, :destroy]
    resource :me, controller: :me, only: [:show, :destroy]
    resource :password, only: [:update]
    resources :accounts, only: [:index, :show]
    resources :users, only: [:create]
    resources :notification_tokens, param: :token, only: [:create, :destroy]
  end
end

resources :api_tokens
