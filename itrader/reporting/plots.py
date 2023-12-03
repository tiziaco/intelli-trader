import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots



CHART_THEME = 'plotly_dark'  # others include seaborn, ggplot2, plotly_dark, plotly_white


def line_equity (portfolio_metrics):
    """
    Plot a line chart with the strategy returns.
    """
    chart = go.Figure()  # generating a figure that will be updated in the following lines
    chart.add_trace(go.Scatter(x=portfolio_metrics.index, y=portfolio_metrics.iloc[:],
                        mode='lines',  # you can also use "lines+markers", or just "markers"
                        name='Strategy Returns',
                        line = dict(color='green')))
    chart.update_layout(template = CHART_THEME,
                        margin = dict(t=50, b=50, l=25, r=25),
                        height=500,
                        plot_bgcolor= 'rgba(0, 0, 0, 0)',
                        paper_bgcolor= 'rgba(0, 0, 0, 0)')
    #chart.update_layout(margin = dict(t=50, b=50, l=25, r=25))  # this will help you optimize the chart space
    chart.update_layout(
                        xaxis_tickfont_size=12,
                        yaxis=dict(
                            title='[%]',
                            titlefont_size=14,
                            tickfont_size=12,
                            ))
    chart.update_layout(showlegend=True)
    # chart.update_xaxes(rangeslider_visible=False)
    # OK, FUNZIONA
    return chart


def line_drwdwn (df):
    """
    Plot the Drawdown
    """
    chart = go.Figure()  # generating a figure that will be updated in the following lines
    chart.add_trace(go.Scatter(x=df.index, y=df.iloc[:],
                        mode='lines',  # you can also use "lines+markers", or just "markers"
                        name='DrawDown',
                        line = dict(color='red'),
                        fill='tozeroy'))
    chart.layout.template = CHART_THEME
    chart.layout.height=300
    chart.update_layout(margin = dict(t=50, b=50, l=25, r=25))  # this will help you optimize the chart space
    chart.update_layout(
        xaxis_tickfont_size=12,
        yaxis=dict(
            title='[%]',
            titlefont_size=14,
            tickfont_size=12,
            ))
    chart.update_layout(showlegend=False)
    # chart.update_xaxes(rangeslider_visible=False)
    # OK, FUNZIONA
    return chart


def profit_loss_scatter(positions, index):
    """
    Scatter plot with the positions returns
    """
    profit = positions[(positions["trade_return"] > 0)][['exit_date', 'trade_return']].set_index('exit_date').reindex(index)*100
    loss = positions[(positions["trade_return"] <= 0)][['exit_date', 'trade_return']].set_index('exit_date').reindex(index)*100
    profit = profit.reset_index()
    loss = loss.reset_index()

    # Markers size
    sizeref = 10*max(round(abs(positions['trade_return']),1))/(6**2)

    chart = go.Figure()  # generating a figure that will be updated in the following lines
    chart.add_trace(go.Scatter(x=profit.date, y=profit.trade_return,
                        mode='markers',  # you can also use "lines+markers", or just "markers"
                        name='profit',
                        marker=dict(
                            size=list(round(abs(profit['trade_return'].fillna(0)),2)),
                            sizemode='area',
                            sizeref=sizeref,
                            sizemin=5),
                        marker_color = 'green',
                        marker_symbol='triangle-up'))
    
    chart.add_trace(go.Scatter(x=loss.date, y=loss.trade_return,
                        mode='markers',  # you can also use "lines+markers", or just "markers"
                        name='loss',
                        marker=dict(
                            size=list(round(abs(loss['trade_return'].fillna(0)),2)),
                            sizemode='area',
                            sizeref=sizeref,
                            sizemin=5),
                        marker_color = 'red',
                        marker_symbol='triangle-down'))
    
    chart.layout.template = CHART_THEME
    chart.layout.height=300
    chart.update_layout(margin = dict(t=50, b=50, l=25, r=25))  # this will help you optimize the chart space
    chart.update_layout(
        xaxis_tickfont_size=12,
        xaxis=dict(
            showgrid=False),
        yaxis=dict(
            title='Profit / Loss [%]',
            titlefont_size=14,
            tickfont_size=12,
            ))
    chart.update_layout(showlegend=False)
    # chart.update_xaxes(rangeslider_visible=False)
    # OK, FUNZIONA
    return chart

def signals_plot (price, transactions):
    """
    Plot a line chart with the strategy signals.
    """
    symbol = np.where(transactions.action == 'ENTRY', 'circle', 'circle-open')
    hover_text=[]
    df_dict = transactions.to_dict('records')

    for row in df_dict:
        hover_text.append(('{date}<br>'+
                        'Direction: {direction}<br>'+
                        'Action: {action}<br>'+
                        'Price: {price}').format(date=row['date'].strftime("%Y/%m/%d, %H:%M"),
                                                    direction=row['direction'],
                                                    action = row['action'],
                                                    price=round(row['price'],2)
                                                    ))
    
    chart = go.Figure()  # generating a figure that will be updated in the following lines
    chart.add_trace(go.Scatter(x=price.index, y=price.close,
                        mode='lines',  # you can also use "lines+markers", or just "markers"
                        name='Close price',
                        hoverinfo='skip',
                        line = dict(color='lightgray')))
    chart.add_trace(go.Scatter(x=transactions.date, y=transactions.price,
                        mode='markers',  # you can also use "lines+markers", or just "markers"
                        name='Signals',
                        text=hover_text,
                        hoverinfo='text',
                        marker=dict(size=10),
                        marker_color = 'blue',
                        marker_symbol=symbol))
    chart.update_layout(template = CHART_THEME,
                        margin = dict(t=50, b=50, l=25, r=25),
                        height=500,
                        plot_bgcolor= 'rgba(0, 0, 0, 0)',
                        paper_bgcolor= 'rgba(0, 0, 0, 0)')
    #chart.update_layout(margin = dict(t=50, b=50, l=25, r=25))  # this will help you optimize the chart space
    chart.update_layout(
                        xaxis_tickfont_size=12,
                        yaxis=dict(
                            title='Price [$]',
                            titlefont_size=14,
                            tickfont_size=12,
                            ))
    chart.update_layout(showlegend=True)
    # chart.update_xaxes(rangeslider_visible=False)
    # OK, FUNZIONA
    return chart


### Sub-plot Equity - Drawdown - Positions
def sub_plots3(plt_1, plt_2, plt_3):
    chart = make_subplots(rows=3, cols=1,
                          subplot_titles=('Equity Line', 'Drawdown', 'Profit / Loss'),
                          row_heights=[0.6, 0.2, 0.2],
                          shared_xaxes=True,
                          vertical_spacing=0.05)
    
    chart.append_trace(plt_1['data'][0],
                       row=1, col=1)

    chart.append_trace(plt_2['data'][0],
                       row=2, col=1)
    
    chart.append_trace(plt_3['data'][0],
                       row=3, col=1)
    chart.append_trace(plt_3['data'][1],
                       row=3, col=1)
    
    chart.update_yaxes(row=2, col=1, autorange='reversed')
    chart.update_layout(template = CHART_THEME,
                        margin = dict(t=50, b=50, l=25, r=25),
                        height=1000,
                        plot_bgcolor= 'rgba(0, 0, 0, 0)',
                        paper_bgcolor= 'rgba(0, 0, 0, 0)')
    return chart