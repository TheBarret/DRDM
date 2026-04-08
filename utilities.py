import numpy as np

class Vec3:
    """A 3D vector class backed by NumPy."""

    __slots__ = ("_v",)

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self._v = np.array([x, y, z], dtype=np.float64)

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #
    @property
    def x(self): return self._v[0]
    @x.setter
    def x(self, val): self._v[0] = val

    @property
    def y(self): return self._v[1]
    @y.setter
    def y(self, val): self._v[1] = val

    @property
    def z(self): return self._v[2]
    @z.setter
    def z(self, val): self._v[2] = val

    # ------------------------------------------------------------------ #
    # Arithmetic
    # ------------------------------------------------------------------ #
    def __add__(self, other):  return Vec3(*self._v + self._coerce(other))
    def __sub__(self, other):  return Vec3(*self._v - self._coerce(other))
    def __mul__(self, scalar): return Vec3(*self._v * scalar)
    def __rmul__(self, scalar): return self.__mul__(scalar)
    def __truediv__(self, scalar): return Vec3(*self._v / scalar)
    def __neg__(self): return Vec3(*-self._v)
    def __pos__(self): return Vec3(*self._v)

    def __iadd__(self, other): self._v += self._coerce(other); return self
    def __isub__(self, other): self._v -= self._coerce(other); return self
    def __imul__(self, scalar): self._v *= scalar; return self
    def __itruediv__(self, scalar): self._v /= scalar; return self

    # ------------------------------------------------------------------ #
    # Comparison
    # ------------------------------------------------------------------ #
    def __eq__(self, other):
        return np.array_equal(self._v, self._coerce(other))

    def __repr__(self):
        return f"Vec3({self._v[0]}, {self._v[1]}, {self._v[2]})"

    def __iter__(self):
        return iter(self._v)

    def __getitem__(self, idx):
        return self._v[idx]

    # ------------------------------------------------------------------ #
    # Vector operations
    # ------------------------------------------------------------------ #
    def dot(self, other) -> float:
        """Dot product."""
        return float(np.dot(self._v, self._coerce(other)))

    def cross(self, other) -> "Vec3":
        """Cross product."""
        return Vec3(*np.cross(self._v, self._coerce(other)))

    def length(self) -> float:
        """Euclidean length (magnitude)."""
        return float(np.linalg.norm(self._v))

    def length_sq(self) -> float:
        """Squared length — avoids sqrt when only relative size matters."""
        return float(np.dot(self._v, self._v))

    def normalize(self) -> "Vec3":
        """Return a unit vector (does not modify in place)."""
        n = self.length()
        if n == 0.0:
            raise ZeroDivisionError("Cannot normalize a zero vector.")
        return Vec3(*self._v / n)

    def distance_to(self, other) -> float:
        """Euclidean distance to another Vec3."""
        return float(np.linalg.norm(self._v - self._coerce(other)))

    def lerp(self, other, t: float) -> "Vec3":
        """Linear interpolation: self + t * (other - self), t in [0, 1]."""
        return Vec3(*((1 - t) * self._v + t * self._coerce(other)))

    def reflect(self, normal: "Vec3") -> "Vec3":
        """Reflect this vector about a surface normal (normal need not be unit)."""
        n = self._coerce(normal)
        return Vec3(*(self._v - 2 * np.dot(self._v, n) * n))

    def angle_to(self, other) -> float:
        """Angle in radians between this vector and another."""
        cos_a = np.dot(self._v, self._coerce(other)) / (self.length() * Vec3(*self._coerce(other)).length())
        return float(np.arccos(np.clip(cos_a, -1.0, 1.0)))

    def to_list(self) -> list:
        return self._v.tolist()

    def to_tuple(self) -> tuple:
        return tuple(self._v.tolist())

    def to_numpy(self) -> np.ndarray:
        return self._v.copy()

    # ------------------------------------------------------------------ #
    # Class / static helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def from_iterable(cls, it) -> "Vec3":
        vals = list(it)
        return cls(*vals[:3])

    @staticmethod
    def zero() -> "Vec3":   return Vec3(0, 0, 0)
    @staticmethod
    def one() -> "Vec3":    return Vec3(1, 1, 1)
    @staticmethod
    def up() -> "Vec3":     return Vec3(0, 1, 0)
    @staticmethod
    def right() -> "Vec3":  return Vec3(1, 0, 0)
    @staticmethod
    def forward() -> "Vec3": return Vec3(0, 0, 1)

    # ------------------------------------------------------------------ #
    # Internal helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce(other) -> np.ndarray:
        if isinstance(other, Vec3):
            return other._v
        return np.asarray(other, dtype=np.float64)