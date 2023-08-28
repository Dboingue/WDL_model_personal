import json, argparse, numpy as np, matplotlib.pyplot as plt
from collections import Counter
from ast import literal_eval
from scipy.interpolate import griddata
from scipy.optimize import curve_fit

parser = argparse.ArgumentParser(
    description="Fit Stockfish's WDL model to fishtest game statistics.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    "filename",
    nargs="?",
    help="json file with fishtest games' WDL statistics",
    default="scoreWDLstat.json",
)
parser.add_argument(
    "--NormalizeToPawnValue",
    type=int,
    default=328,
    help="Value needed for converting the games' cp scores to the SF's internal score.",
)
parser.add_argument(
    "--moveTarget",
    type=int,
    default=32,
    help="Move at which new rescaled 100cp should correspond to 50:50 winning chances.",
)
parser.add_argument(
    "--show",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="Show graphics or not. An image is always saved. Useful for batch processing.",
)
args = parser.parse_args()

print(f"Reading score stats from {args.filename}.")
with open(args.filename) as infile:
    inputdata = json.load(infile)

print(f"Converting scores with NormalizeToPawnValue = {args.NormalizeToPawnValue}.")
inpdict = {literal_eval(k): v for k, v in inputdata.items()}
win, draw, loss = Counter(), Counter(), Counter()
# filter out (score, move) WDL data (i.e. material summed out)
for (result, move, _, score), v in inpdict.items():
    # exclude large scores and the endings of very long games
    if abs(score) > 400 or move < 0 or move > 120:
        continue

    # convert the cp score to the internal value
    score = score * args.NormalizeToPawnValue / 100

    if result == "W":
        win[score, move] += v
    elif result == "D":
        draw[score, move] += v
    elif result == "L":
        loss[score, move] += v

print(
    f"Retained (W,D,L) = ({sum(win.values())}, {sum(draw.values())}, {sum(loss.values())}) positions."
)

# create (score, move) -> WDL ratio data
coords = sorted(set(list(win.keys()) + list(draw.keys()) + list(loss.keys())))
xs, ys, zwins, zdraws, zlosses = [], [], [], [], []
for x, y in coords:
    xs.append(x)
    ys.append(y)
    total = win[x, y] + draw[x, y] + loss[x, y]
    zwins.append(win[x, y] / total)
    zdraws.append(draw[x, y] / total)
    zlosses.append(loss[x, y] / total)

#
# fit a model to predict winrate from score and move
# define model functions
#


def winmodel(x, a, b):
    return 1.0 / (1.0 + np.exp(-(x - a) / b))


def poly3(x, a, b, c, d):
    xnp = np.asarray(x) / args.moveTarget
    return ((a * xnp + b) * xnp + c) * xnp + d


def poly3_str(coeffs):
    return (
        "((%5.3f * x / %d + %5.3f) * x / %d + %5.3f) * x / %d + %5.3f"
        % tuple(val for pair in zip(coeffs, [args.moveTarget] * 4) for val in pair)[:-1]
    )


def wdl(score, move, popt_as, popt_bs):
    a = poly3(move, *popt_as)
    b = poly3(move, *popt_bs)
    w = int(1000 * winmodel(score, a, b))
    l = int(1000 * winmodel(-score, a, b))
    d = 1000 - w - l
    return w, d, l


def normalized_axis(ax):
    ax2 = ax.twiny()
    tickmin = int(np.ceil(ax.get_xlim()[0] / args.NormalizeToPawnValue)) * 2
    tickmax = int(np.floor(ax.get_xlim()[1] / args.NormalizeToPawnValue)) * 2 + 1
    new_tick_locations = np.array(
        [x / 2 * args.NormalizeToPawnValue for x in range(tickmin, tickmax)]
    )

    def tick_function(X):
        V = X / args.NormalizeToPawnValue
        return [(f"{z:.0f}" if z % 1 < 0.1 else "") for z in V]

    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(new_tick_locations)
    ax2.set_xticklabels(tick_function(new_tick_locations))


fig, axs = plt.subplots(
    2, 3, figsize=(11.69 * 1.5, 8.27 * 1.5), constrained_layout=True
)
fig.suptitle("Summary of win-draw-loss model analysis", fontsize="x-large")

#
# convert to model, fit the winmodel a and b,
# for a given value of the move counter
#
scores, moves, winrate, drawrate, lossrate = xs, ys, zwins, zdraws, zlosses

model_ms, model_as, model_bs = [], [], []

grouping = 1
for m in range(3, 120, grouping):
    mmin = m
    mmax = m + grouping
    xdata, ydata, ydrawdata, ylossdata = [], [], [], []
    for i in range(0, len(moves)):
        if moves[i] < mmin or moves[i] >= mmax:
            continue
        xdata.append(scores[i])
        ydata.append(winrate[i])
        ydrawdata.append(drawrate[i])
        ylossdata.append(lossrate[i])

    # skip fit for move counts with very few data points
    if len(ydata) < 10:
        continue

    popt, pcov = curve_fit(
        winmodel,
        xdata,
        ydata,
        p0=[args.NormalizeToPawnValue, args.NormalizeToPawnValue / 6],
    )
    model_ms.append(m)
    model_as.append(popt[0])
    model_bs.append(popt[1])

    # plot sample curve at moveTarget
    if m == args.moveTarget:
        axs[0, 0].plot(xdata, ydata, "b.", label="Measured winrate")
        axs[0, 0].plot(xdata, ydrawdata, "g.", label="Measured drawrate")
        axs[0, 0].plot(xdata, ylossdata, "c.", label="Measured lossrate")

        ymodel = []
        for x in xdata:
            ymodel.append(winmodel(x, popt[0], popt[1]))
        axs[0, 0].plot(xdata, ymodel, "r-", label="Model")

        ymodel = []
        for x in xdata:
            ymodel.append(winmodel(-x, popt[0], popt[1]))
        axs[0, 0].plot(xdata, ymodel, "r-")

        ymodel = []
        for x in xdata:
            ymodel.append(
                1 - winmodel(x, popt[0], popt[1]) - winmodel(-x, popt[0], popt[1])
            )
        axs[0, 0].plot(xdata, ymodel, "r-")

        axs[0, 0].set_xlabel("Evaluation [lower: Internal Value units, upper: Pawns]")
        axs[0, 0].set_ylabel("outcome")
        axs[0, 0].legend(fontsize="small")
        axs[0, 0].set_title(
            f"Comparison of model and measured data at move {args.moveTarget}"
        )
        xmax = ((3 * args.NormalizeToPawnValue) // 100 + 1) * 100
        axs[0, 0].set_xlim([-xmax, xmax])
        normalized_axis(axs[0, 0])


#
# now capture the functional behavior of a and b as a function of the move counter
# simple polynomial fit
#

# fit a and b
popt_as, pcov = curve_fit(poly3, model_ms, model_as)
popt_bs, pcov = curve_fit(poly3, model_ms, model_bs)
label_as, label_bs = "as = " + poly3_str(popt_as), "bs = " + poly3_str(popt_bs)

#
# now we can define the conversion factor from internal score to centipawn such that
# an expected win score of 50% is for a score of 'a', we pick this value for the moveTarget
# (where the sum of the a coefs is equal to the interpolated a).
fsum_a = sum(popt_as)
fsum_b = sum(popt_bs)
print(f"const int NormalizeToPawnValue = {int(fsum_a)};")
print(f"Corresponding spread = {int(fsum_b)};")
print(f"Corresponding normalized spread = {fsum_b / fsum_a};")
print(
    f"Draw rate at 0.0 eval at move {args.moveTarget} = {1 - 2 / (1 + np.exp(fsum_a / fsum_b))};"
)

print("Parameters in internal value units: ")

# give as output as well
print(label_as)
print(label_bs)
print("     constexpr double as[] = {%13.8f, %13.8f, %13.8f, %13.8f};" % tuple(popt_as))
print(
    "     constexpr double bs[] = {%13.8f, %13.8f, %13.8f, %13.8f };" % tuple(popt_bs)
)

# graphs of a and b as a function of the move number
print("Plotting move dependence of model parameters.")
axs[1, 0].plot(model_ms, model_as, "b.", label="as")
axs[1, 0].plot(model_ms, poly3(model_ms, *popt_as), "r-", label="fit: " + label_as)
axs[1, 0].plot(model_ms, model_bs, "g.", label="bs")
axs[1, 0].plot(model_ms, poly3(model_ms, *popt_bs), "m-", label="fit: " + label_bs)

axs[1, 0].set_xlabel("move")
axs[1, 0].set_ylabel("parameters (in internal value units)")
axs[1, 0].legend(fontsize="x-small")
axs[1, 0].set_title("Winrate model parameters")
axs[1, 0].set_ylim(bottom=0.0)

#
# now generate contour plots
#
contourlines = [0, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.97, 1.0]

print("Processing done, plotting 2D data.")
for i in [0, 1]:
    for j in [1, 2]:
        axs[i, j].yaxis.grid(True)
        axs[i, j].xaxis.grid(True)
        axs[i, j].set_xlabel("Evaluation [lower: Internal Value units, upper: Pawns]")
        axs[i, j].set_ylabel("move")

# for wins
xmin = -((1 * args.NormalizeToPawnValue) // 100 + 1) * 100
xmax = ((3 * args.NormalizeToPawnValue) // 100 + 1) * 100
grid_x, grid_y = np.mgrid[xmin:xmax:30j, 10:120:22j]
points = np.array(list(zip(xs, ys)))

# data
zz = griddata(points, zwins, (grid_x, grid_y), method="linear")
cp = axs[0, 1].contourf(grid_x, grid_y, zz, contourlines)
fig.colorbar(cp, ax=axs[:, 2], shrink=0.618)
CS = axs[0, 1].contour(grid_x, grid_y, zz, contourlines, colors="black")
axs[0, 1].clabel(CS, inline=1, colors="black")
axs[0, 1].set_title("Data: Fraction of positions leading to a win")
normalized_axis(axs[0, 1])

# model
for i in range(0, len(xs)):
    zwins[i] = wdl(xs[i], ys[i], popt_as, popt_bs)[0] / 1000.0
zz = griddata(points, zwins, (grid_x, grid_y), method="linear")
cp = axs[1, 1].contourf(grid_x, grid_y, zz, contourlines)
CS = axs[1, 1].contour(grid_x, grid_y, zz, contourlines, colors="black")
axs[1, 1].clabel(CS, inline=1, colors="black")
axs[1, 1].set_title("Model: Fraction of positions leading to a win")
normalized_axis(axs[1, 1])

# for draws
xmin = -((2 * args.NormalizeToPawnValue) // 100 + 1) * 100
xmax = ((2 * args.NormalizeToPawnValue) // 100 + 1) * 100
grid_x, grid_y = np.mgrid[xmin:xmax:30j, 10:120:22j]
points = np.array(list(zip(xs, ys)))

# data
zz = griddata(points, zdraws, (grid_x, grid_y), method="linear")
cp = axs[0, 2].contourf(grid_x, grid_y, zz, contourlines)
CS = axs[0, 2].contour(grid_x, grid_y, zz, contourlines, colors="black")
axs[0, 2].clabel(CS, inline=1, colors="black")
axs[0, 2].set_title("Data: Fraction of positions leading to a draw")
normalized_axis(axs[0, 2])

# for wins, draws
for i in range(0, len(xs)):
    zwins[i] = wdl(xs[i], ys[i], popt_as, popt_bs)[1] / 1000.0
zz = griddata(points, zwins, (grid_x, grid_y), method="linear")
cp = axs[1, 2].contourf(grid_x, grid_y, zz, contourlines)
CS = axs[1, 2].contour(grid_x, grid_y, zz, contourlines, colors="black")
axs[1, 2].clabel(CS, inline=1, colors="black")
axs[1, 2].set_title("Model: Fraction of positions leading to a draw")
normalized_axis(axs[1, 2])


fig.align_labels()

plt.savefig("WDL_model_summary.png", dpi=300)
if args.show:
    plt.show()
plt.close()
print("Saved graphics to WDL_model_summary.png.")