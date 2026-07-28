interface ProductIdentityProps {
  name: string;
  sku: string;
  category?: string | null;
}

export function ProductIdentity({ name, sku, category }: ProductIdentityProps) {
  return <div className="product-cell">
    <strong className="product-name">{name}</strong>
    <span className="product-sku">SKU: {sku}</span>
    {category && <small className="product-category">{category}</small>}
  </div>;
}
