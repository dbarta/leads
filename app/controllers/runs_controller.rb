class RunsController < ApplicationController
  before_action :authenticate_user!
  before_action :set_run, only: [:show, :edit, :update]

  def index
    @runs = Run.order(created_at: :desc)
  end

  def show
  end

  def new
    @run = Run.new
  end

  def create
    @run = Run.new(run_params)
    if @run.save
      redirect_to @run, notice: "Run created."
    else
      render :new, status: :unprocessable_entity
    end
  end

  def edit
  end

  def update
    if @run.update(run_params)
      redirect_to @run, notice: "Run updated."
    else
      render :edit, status: :unprocessable_entity
    end
  end

  private

  def set_run
    @run = Run.find(params[:id])
  end

  def run_params
    params.require(:run).permit(:name, :airports, :naics_codes, :processes, :notes, :started_at, :completed_at)
  end
end
