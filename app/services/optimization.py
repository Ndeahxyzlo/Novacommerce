import numpy as np

TOLERANCE = 1e-9
SINGULAR_TOLERANCE = 1e-10
MAX_ITERATIONS = 20000


class SingularSystem(ValueError):
    pass


def as_system(a, b):
    matrix = np.array(a, dtype=float)
    vector = np.array(b, dtype=float).reshape(-1)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] != vector.shape[0]:
        raise ValueError("el sistema debe ser cuadrado y compatible con el vector de terminos independientes")
    return matrix, vector


def solve_elimination(a, b):
    matrix, vector = as_system(a, b)
    size = matrix.shape[0]
    augmented = np.hstack([matrix, vector.reshape(-1, 1)])
    for column in range(size):
        pivot = column + int(np.argmax(np.abs(augmented[column:, column])))
        if abs(augmented[pivot, column]) <= SINGULAR_TOLERANCE:
            raise SingularSystem("el sistema no tiene solucion unica")
        if pivot != column:
            augmented[[column, pivot]] = augmented[[pivot, column]]
        augmented[column] = augmented[column] / augmented[column, column]
        for row in range(size):
            if row != column:
                augmented[row] = augmented[row] - augmented[row, column] * augmented[column]
    return augmented[:, -1].copy()


def solve_substitution(a, b):
    matrix, vector = as_system(a, b)
    size = matrix.shape[0]
    if size == 1:
        if abs(matrix[0, 0]) <= SINGULAR_TOLERANCE:
            raise SingularSystem("el sistema no tiene solucion unica")
        return np.array([vector[0] / matrix[0, 0]])
    pivot = int(np.argmax(np.abs(matrix[:, 0])))
    if abs(matrix[pivot, 0]) <= SINGULAR_TOLERANCE:
        raise SingularSystem("el sistema no tiene solucion unica")
    others = [row for row in range(size) if row != pivot]
    reduced_a = np.zeros((size - 1, size - 1))
    reduced_b = np.zeros(size - 1)
    for position, row in enumerate(others):
        factor = matrix[row, 0] / matrix[pivot, 0]
        reduced_a[position] = matrix[row, 1:] - factor * matrix[pivot, 1:]
        reduced_b[position] = vector[row] - factor * vector[pivot]
    tail = solve_substitution(reduced_a, reduced_b)
    first = (vector[pivot] - matrix[pivot, 1:] @ tail) / matrix[pivot, 0]
    return np.concatenate([[first], tail])


def simplex_max(c, a, b, record=False):
    c = np.array(c, dtype=float).reshape(-1)
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float).reshape(-1)
    rows, columns = a.shape
    if c.shape[0] != columns or b.shape[0] != rows:
        raise ValueError("dimensiones incompatibles")
    if np.any(b < -TOLERANCE):
        raise ValueError("los terminos independientes deben ser no negativos")

    tableau = np.zeros((rows + 1, columns + rows + 1))
    tableau[:rows, :columns] = a
    tableau[:rows, columns : columns + rows] = np.eye(rows)
    tableau[:rows, -1] = b
    tableau[rows, :columns] = -c
    basis = list(range(columns, columns + rows))
    snapshots = [tableau.copy()] if record else []
    pivots = []
    degenerate_steps = 0
    use_bland = False

    while True:
        reduced = tableau[rows, :-1]
        negative = np.where(reduced < -TOLERANCE)[0]
        if negative.size == 0:
            break
        entering = int(negative[0]) if use_bland else int(np.argmin(reduced))
        column = tableau[:rows, entering]
        positive = column > TOLERANCE
        if not positive.any():
            return {"status": "unbounded", "x": None, "objective": None, "duals": None, "pivots": pivots, "tableaus": snapshots, "basis": basis}
        ratios = np.full(rows, np.inf)
        ratios[positive] = tableau[:rows, -1][positive] / column[positive]
        minimum = float(ratios.min())
        ties = [int(r) for r in np.where(ratios <= minimum + TOLERANCE)[0]]
        leaving = min(ties, key=lambda r: basis[r])
        if minimum <= TOLERANCE:
            degenerate_steps += 1
            if degenerate_steps > rows + columns:
                use_bland = True
        else:
            degenerate_steps = 0
        tableau[leaving] = tableau[leaving] / tableau[leaving, entering]
        for row in range(rows + 1):
            if row != leaving:
                tableau[row] = tableau[row] - tableau[row, entering] * tableau[leaving]
        pivots.append((entering, basis[leaving]))
        basis[leaving] = entering
        if record:
            snapshots.append(tableau.copy())
        if len(pivots) > MAX_ITERATIONS:
            raise RuntimeError("el simplex no converge")

    x = np.zeros(columns)
    for row, variable in enumerate(basis):
        if variable < columns:
            x[variable] = tableau[row, -1]
    return {
        "status": "optimal",
        "x": x,
        "objective": float(tableau[rows, -1]),
        "duals": tableau[rows, columns : columns + rows].copy(),
        "pivots": pivots,
        "tableaus": snapshots,
        "basis": basis,
    }


def verify_vertex(a, b, x, tolerance=1e-7):
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float).reshape(-1)
    x = np.array(x, dtype=float).reshape(-1)
    size = x.shape[0]
    rows = np.vstack([a, -np.eye(size)])
    rhs = np.concatenate([b, np.zeros(size)])
    gap = rhs - rows @ x
    active = [int(i) for i in np.where(np.abs(gap) <= tolerance)[0]]
    chosen = []
    for index in active:
        trial = chosen + [index]
        if np.linalg.matrix_rank(rows[trial]) == len(trial):
            chosen = trial
        if len(chosen) == size:
            break
    if len(chosen) < size:
        return {"verified": False, "active": chosen, "solution": None}
    solved = solve_elimination(rows[chosen], rhs[chosen])
    return {"verified": bool(np.allclose(solved, x, atol=1e-6)), "active": chosen, "solution": solved}
