import numpy as np
import deepnet
import deepnet.utils as utils


class Node:

    def __init__(self, context, next_functions=None):
        self.context = context
        self.next_functions = next_functions

    def apply(self, grad):
        next_grads = self.context.apply(grad)
        if self.next_functions:
            self._apply_next_functions(
                self.next_functions, next_grads)

    def _apply_next_functions(self, next_functions, next_grads):
        next_grads = _preprocess_grad_output(next_grads)
        for next_function, grad in zip(next_functions, next_grads):
            if next_function is not None:
                next_function.apply(grad)

    @classmethod
    def with_context(cls, context, next_functions):
        return cls(context, next_functions)

    def __repr__(self) -> str:
        return str(self.context.__class__.__name__)


def _preprocess_grad_output(grad):
    if deepnet.is_tensor(grad):
        grad = (grad,)
    return grad


class AccumulateGrad:

    def __init__(self, tensor) -> None:
        self.tensor = tensor

    def apply(self, grad):
        if self.tensor.grad is None:
            self.tensor.grad = deepnet.zeros_like(self.tensor)
        grad_data = _process_grad_for_accumulate(self.tensor, grad)
        self.tensor.grad.data += grad_data.data

    @classmethod
    def with_tensor(cls, tensor):
        return cls(tensor)


def _process_grad_for_accumulate(tensor, grad):
    if tensor.dim() != grad.dim():
        if utils.is_scalar_tensor(tensor):
            return np.sum(
                grad.data, axis=grad.dim(),
                keepdims=False)
        dims = _get_dims_to_sum(tensor.dim(), grad.dim())
        keepdims = tensor.ndim() == grad.ndim()
        return np.sum(grad.data, axis=dims, keepdims=keepdims)
    return grad.data


def _get_dims_to_sum(dim_1, dim_2):
    diff = len(dim_2) - len(dim_1)
    padded_dim_1 = [1] * diff + list(dim_1)
    return tuple([i for i in range(len(dim_2))
                  if dim_2[i] != padded_dim_1[i]])


def _pass_to_graph(context, output):
    if deepnet.grad_enabled():
        output = _pass_for_reverse_ad(context, output)
    if deepnet.forward_ad_enabled():
        output = _pass_for_forward_ad(context, output)
    return output


def _pass_for_forward_ad(context, output):
    saved_tensors = _preprocess_for_forward_ad(context)
    tangents = [dual_tensor.tangent
                for dual_tensor in saved_tensors]
    tangent_out = context.apply_jvp(*tangents)
    output._set_dual_state(tangent_out, True)
    return output


def _preprocess_for_forward_ad(context):
    return [tensor if tensor.in_dual else tensor.dual(
        inplace=False) for tensor in context.saved_tensors()]
    

def _pass_for_reverse_ad(context, output):
    if _context_has_grad_tensors(context):
        next_functions = _get_next_functions(context.saved_tensors())
        node = Node.with_context(context, next_functions)
        output._set_grad_state(
            use_grad=True, grad_fn=node, is_leaf=False)
    return output


def _context_has_grad_tensors(context):
    if context.saved_tensors():
        return any(tensor.use_grad
                   for tensor in context.saved_tensors())
    return False


def _get_next_functions(saved_tensors):
    next_functions = []
    for tensor in saved_tensors:
        next_function = _get_next_functions_helper(
            tensor)
        next_functions.append(next_function)
    return tuple(next_functions)


def _get_next_functions_helper(tensor):
    if tensor.is_leaf and tensor.use_grad:
        context = AccumulateGrad.with_tensor(tensor)
        return Node.with_context(context, next_functions=None)
    return tensor.grad_fn
