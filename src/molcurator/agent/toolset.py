"""The four tool functions the agent calls, bundled so tests can swap in fakes (Phase 2, R2.2, R2.3)."""
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Toolset:
    generate: Callable  # exact signatures: see molcurator.tools.generate / predict / train / validate / curate
    predict: Callable
    train: Callable  # train() and ml_predict() both live in molcurator.tools.train
    ml_predict: Callable
    validate: Callable
    curate: Callable

    @classmethod
    def default(cls, predict_settings=None, train_settings=None) -> "Toolset":
        """The real tools. Imported here, so code that only uses fakes never loads their dependencies.
        predict_settings (the run config's predict: section) sets PREDICT's method and basis;
        train_settings (its train: section) TRAIN's model and whether it refits the saved model on every example."""
        from molcurator.tools import curate, generate, predict, train, validate
        method = predict_settings.method if predict_settings else None
        basis = predict_settings.basis if predict_settings else None
        refit = bool(train_settings and train_settings.refit_on_all)
        model = train_settings.model if train_settings else train.DEFAULT_MODEL
        return cls(generate.generate, predict.predict_at(method, basis), train.train_with(refit, model), train.ml_predict,
                   validate.validate, curate.curate)

    @classmethod
    def from_object(cls, tools) -> "Toolset":
        """Any object with the four methods, e.g. FakeTools in tests."""
        return cls(tools.generate, tools.predict, tools.train, tools.ml_predict, tools.validate, tools.curate)
