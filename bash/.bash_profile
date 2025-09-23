export PATH=$PATH:/Users/avanindra.pandeya/.HelloTech/bin
export GITHUB_TOKEN=<value>
export KUBECONFIG=~/.kube/config:~/.kube/eksconfig
alias k=kubectl
alias ks='kubectl config use-context upn-eks-staging'
alias kl='kubectl config use-context upn-eks-live'
alias gt=git
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"

source ~/.zprofile
